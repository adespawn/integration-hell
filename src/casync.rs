#![deny(clippy::all)]
#![allow(clippy::arc_with_non_send_sync)]

use std::cell::RefCell;
use std::collections::HashMap;
use std::ffi::CString;
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, RawWaker, RawWakerVTable, Waker};

use napi::bindgen_prelude::*;
use napi::threadsafe_function::ThreadsafeFunctionCallMode;
use napi::sys;
use napi_derive::napi;

// ---------------------------------------------------------------------------
// JsPromise — lightweight wrapper so #[napi] fns can return a raw Promise
// without lifetime issues (Object<'_> can't be returned from #[napi] fns).
// ---------------------------------------------------------------------------

pub struct JsPromise(sys::napi_value);

impl ToNapiValue for JsPromise {
  unsafe fn to_napi_value(_: sys::napi_env, val: Self) -> Result<sys::napi_value> {
    Ok(val.0)
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SettleCallback = Box<dyn FnOnce(sys::napi_env, sys::napi_deferred) + Send>;
type BoxFuture = Pin<Box<dyn Future<Output = SettleCallback> + Send>>;

struct FutureEntry {
  future: BoxFuture,
  /// Raw deferred handle — resolved/rejected in `poll_woken` on the
  /// main thread where we have a valid `napi_env`.
  deferred: sys::napi_deferred,
  waker: Waker,
}

// ---------------------------------------------------------------------------
// WakerBridge — single TSFN, coalesced wake signals
// ---------------------------------------------------------------------------

type Tsfn = napi::threadsafe_function::ThreadsafeFunction<(), (), (), Status, false, true, 0>;

struct WakerBridge {
  woken_ids: Arc<Mutex<Vec<u64>>>,
  signaled: Arc<AtomicBool>,
  /// The TSFN lives here (behind a Mutex) so it's reachable from any
  /// thread — including the Tokio worker thread that fires wakers.
  tsfn: Mutex<Option<Tsfn>>,
}

impl WakerBridge {
  fn new() -> Self {
    Self {
      woken_ids: Arc::new(Mutex::new(Vec::new())),
      signaled: Arc::new(AtomicBool::new(false)),
      tsfn: Mutex::new(None),
    }
  }

  /// Set the TSFN after creation (called once from `init_poll_bridge`).
  fn set_tsfn(&self, tsfn: Tsfn) {
    *self.tsfn.lock().unwrap() = Some(tsfn);
  }

  /// Signal the TSFN if not already signaled.
  fn signal(&self) {
    if !self.signaled.swap(true, Ordering::AcqRel) {
      let guard = self.tsfn.lock().unwrap();
      if let Some(ref tsfn) = *guard {
        tsfn.call((), ThreadsafeFunctionCallMode::NonBlocking);
      }
    }
  }

  /// Called from any thread by a Waker.
  fn wake(&self, future_id: u64) {
    {
      let mut ids = self.woken_ids.lock().unwrap();
      ids.push(future_id);
    }
    self.signal();
  }
}

// ---------------------------------------------------------------------------
// Per-future waker internals (RawWakerVTable)
// ---------------------------------------------------------------------------

struct WakerInner {
  future_id: u64,
  bridge: Arc<WakerBridge>,
}

impl WakerInner {
  fn wake_impl(&self) {
    self.bridge.wake(self.future_id);
  }
}

fn make_waker(inner: Arc<WakerInner>) -> Waker {
  let raw = Arc::into_raw(inner) as *const ();

  unsafe fn clone_fn(data: *const ()) -> RawWaker {
    let arc = unsafe { Arc::from_raw(data as *const WakerInner) };
    let cloned = arc.clone();
    std::mem::forget(arc);
    RawWaker::new(Arc::into_raw(cloned) as *const (), &VTABLE)
  }

  unsafe fn wake_fn(data: *const ()) {
    let arc = unsafe { Arc::from_raw(data as *const WakerInner) };
    arc.wake_impl();
  }

  unsafe fn wake_by_ref_fn(data: *const ()) {
    let arc = unsafe { Arc::from_raw(data as *const WakerInner) };
    arc.wake_impl();
    std::mem::forget(arc);
  }

  unsafe fn drop_fn(data: *const ()) {
    drop(unsafe { Arc::from_raw(data as *const WakerInner) });
  }

  static VTABLE: RawWakerVTable =
    RawWakerVTable::new(clone_fn, wake_fn, wake_by_ref_fn, drop_fn);

  unsafe { Waker::from_raw(RawWaker::new(raw, &VTABLE)) }
}

// ---------------------------------------------------------------------------
// FutureRegistry — thread-local, lives on the Node main thread
// ---------------------------------------------------------------------------

const POLL_BUDGET: usize = 128;

struct FutureRegistry {
  futures: HashMap<u64, FutureEntry>,
  next_id: u64,
  bridge: Arc<WakerBridge>,
  tokio_rt: Option<tokio::runtime::Runtime>,
}

impl FutureRegistry {
  fn new() -> Self {
    let bridge = Arc::new(WakerBridge::new());
    Self {
      futures: HashMap::new(),
      next_id: 0,
      bridge,
      tokio_rt: None,
    }
  }

  fn insert(&mut self, future: BoxFuture, deferred: sys::napi_deferred) -> u64 {
    // println!("Inserting future with deferred {deferred:p}");
    let id = self.next_id;
    self.next_id += 1;

    let waker = make_waker(Arc::new(WakerInner {
      future_id: id,
      bridge: Arc::clone(&self.bridge),
    }));

    self.futures.insert(id, FutureEntry { future, deferred, waker });

    // Schedule the mandatory first poll.
    {
      let mut ids = self.bridge.woken_ids.lock().unwrap();
      ids.push(id);
    }
    self.bridge.signal();

    id
  }

  /// Called on the main thread when the TSFN fires.
  /// `raw_env` is valid only for this invocation (from the TSFN callback).
  fn poll_woken(&mut self, raw_env: sys::napi_env) {
    self.bridge.signaled.store(false, Ordering::Release);

    let woken: Vec<u64> = {
      let mut ids = self.bridge.woken_ids.lock().unwrap();
      std::mem::take(&mut *ids)
    };

    let (now, later) = if woken.len() > POLL_BUDGET {
      (&woken[..POLL_BUDGET], &woken[POLL_BUDGET..])
    } else {
      (&woken[..], &[][..])
    };

    if !later.is_empty() {
      let mut ids = self.bridge.woken_ids.lock().unwrap();
      ids.extend_from_slice(later);
      self.bridge.signal();
    }

    // Take-and-process: remove entries before polling so that a polled
    // future can register *new* futures without hitting RefCell deadlock.
    let entries: Vec<(u64, FutureEntry)> = now
      .iter()
      .filter_map(|&id| self.futures.remove(&id).map(|e| (id, e)))
      .collect();

    // Enter the Tokio runtime context so tokio::net, tokio::time, etc.
    // register with the reactor when polled.
    let _guard = self.tokio_rt.as_ref().map(|rt| rt.enter());

    for (id, mut entry) in entries {
      let mut cx = Context::from_waker(&entry.waker);
      match entry.future.as_mut().poll(&mut cx) {
        Poll::Ready(settle_fn) => {
          settle_fn(raw_env, entry.deferred);
        }
        Poll::Pending => {
          self.futures.insert(id, entry);
        }
      }
    }
  }

  fn shutdown(&mut self) {
    self.futures.clear();
    *self.bridge.tsfn.lock().unwrap() = None;
    if let Some(rt) = self.tokio_rt.take() {
      rt.shutdown_background();
    }
  }
}

thread_local! {
  static REGISTRY: RefCell<FutureRegistry> = RefCell::new(FutureRegistry::new());
}

// ---------------------------------------------------------------------------
// No-op C callback for the TSFN's backing JS function.
// The actual work happens in `build_callback`'s Rust closure.
// ---------------------------------------------------------------------------

unsafe extern "C" fn noop_callback(
  _env: sys::napi_env,
  _info: sys::napi_callback_info,
) -> sys::napi_value {
  std::ptr::null_mut()
}

// ---------------------------------------------------------------------------
// NAPI exports
// ---------------------------------------------------------------------------

/// Initialise the direct-poll bridge.  Must be called once before any
/// bridged async function.
///
/// Creates a dedicated `multi_thread(1)` Tokio runtime whose single worker
/// thread drives the reactor (epoll/kqueue).  A single weak TSFN is used
/// as the cross-thread wake mechanism — ABI-stable, cross-platform, no
/// direct libuv dependency.
///
/// Panic handling: if the Tokio worker thread panics the process aborts.
/// This is the simplest strategy — no silent hangs, no orphaned promises.
#[napi]
pub fn init_poll_bridge(env: Env) -> Result<()> {
  // println!("Initializing poll bridge...");
  let rt = tokio::runtime::Builder::new_multi_thread()
    .worker_threads(1)
    .enable_all()
    .build()
    .map_err(|e| Error::from_reason(format!("tokio runtime init failed: {e}")))?;

  // Create the TSFN from a no-op C callback.
  // `build_callback` replaces the JS call — the noop is never invoked.
  let noop_fn = env.create_function::<(), ()>("pollBridgeNoop", noop_callback)?;

  let tsfn = noop_fn
    .build_threadsafe_function::<()>()
    .weak::<true>()
    .build_callback(|ctx| {
      let raw_env = ctx.env.raw();
      REGISTRY.with(|r| {
        r.borrow_mut().poll_woken(raw_env);
      });
      Ok(())
    })?;

  REGISTRY.with(|r| {
    let mut reg = r.borrow_mut();
    reg.tokio_rt = Some(rt);
    reg.bridge.set_tsfn(tsfn);
  });

  // Cleanup hook — shut down the runtime when Node exits.
  env.add_env_cleanup_hook((), |_| {
    REGISTRY.with(|r| {
      r.borrow_mut().shutdown();
    });
  })?;

  Ok(())
}

/// Submit a Rust future to be polled directly by the Node event loop.
///
/// Returns a JS `Promise` that resolves when the future completes with
/// `Ok(())`, or rejects when it completes with `Err(...)`.
///
/// The deferred is resolved/rejected directly via raw NAPI calls inside
/// `poll_woken` (no extra TSFN round-trip since we're already on the
/// main thread).
pub fn submit_future<F>(env: &Env, fut: F) -> Result<JsPromise>
where
  F: Future<Output = Result<()>> + Send + 'static,
{
  let raw_env = env.raw();
  let mut deferred: sys::napi_deferred = std::ptr::null_mut();
  let mut promise: sys::napi_value = std::ptr::null_mut();

  let status = unsafe { sys::napi_create_promise(raw_env, &mut deferred, &mut promise) };
  if status != sys::Status::napi_ok {
    return Err(Error::from_reason("napi_create_promise failed"));
  }

  let boxed: BoxFuture = Box::pin(async move {
    match fut.await {
      Ok(()) => Box::new(|env, deferred| {
        let mut undefined: sys::napi_value = std::ptr::null_mut();
        unsafe {
          sys::napi_get_undefined(env, &mut undefined);
          sys::napi_resolve_deferred(env, deferred, undefined);
        }
      }) as SettleCallback,
      Err(e) => {
        let reason = e.reason.to_string();
        Box::new(move |env, deferred| {
          let c_reason = CString::new(reason.as_str())
            .unwrap_or_else(|_| CString::new("Unknown error").unwrap());
          let mut msg: sys::napi_value = std::ptr::null_mut();
          let mut error: sys::napi_value = std::ptr::null_mut();
          unsafe {
            sys::napi_create_string_utf8(
              env,
              c_reason.as_ptr(),
              c_reason.to_bytes().len() as isize,
              &mut msg,
            );
            sys::napi_create_error(env, std::ptr::null_mut(), msg, &mut error);
            sys::napi_reject_deferred(env, deferred, error);
          }
        }) as SettleCallback
      }
    }
  });

  REGISTRY.with(|r| {
    r.borrow_mut().insert(boxed, deferred);
  });

  Ok(JsPromise(promise))
}

/// Submit a typed Rust future to be polled directly by the Node event loop.
///
/// Like `submit_future`, but the future can return a typed value `T` on success
/// or an error `E` on failure. Both `T` and `E` are converted to JS values via
/// `ToNapiValue` on the main thread when the future settles.
///
/// The error type `E` should produce a JS Error object from `to_napi_value` so
/// that the rejection value is a proper error (e.g. `ConvertedError`).
pub fn submit_future_typed<F, T, E>(env: &Env, fut: F) -> Result<JsPromise>
where
  F: Future<Output = std::result::Result<T, E>> + Send + 'static,
  T: napi::bindgen_prelude::ToNapiValue + Send + 'static,
  E: napi::bindgen_prelude::ToNapiValue + Send + 'static,
{
  let raw_env = env.raw();
  let mut deferred: sys::napi_deferred = std::ptr::null_mut();
  let mut promise: sys::napi_value = std::ptr::null_mut();

  let status = unsafe { sys::napi_create_promise(raw_env, &mut deferred, &mut promise) };
  if status != sys::Status::napi_ok {
    return Err(Error::from_reason("napi_create_promise failed"));
  }

  let boxed: BoxFuture = Box::pin(async move {
    match fut.await {
      Ok(val) => Box::new(move |env, deferred| match unsafe { T::to_napi_value(env, val) } {
        Ok(v) => unsafe { sys::napi_resolve_deferred(env, deferred, v); },
        Err(e) => {
          let c_reason = CString::new(e.reason.as_str())
            .unwrap_or_else(|_| CString::new("Unknown error").unwrap());
          let mut msg: sys::napi_value = std::ptr::null_mut();
          let mut error: sys::napi_value = std::ptr::null_mut();
          unsafe {
            sys::napi_create_string_utf8(
              env,
              c_reason.as_ptr(),
              c_reason.to_bytes().len() as isize,
              &mut msg,
            );
            sys::napi_create_error(env, std::ptr::null_mut(), msg, &mut error);
            sys::napi_reject_deferred(env, deferred, error);
          }
        }
      }) as SettleCallback,
      Err(err) => Box::new(move |env, deferred| match unsafe { E::to_napi_value(env, err) } {
        Ok(js_err) => unsafe { sys::napi_reject_deferred(env, deferred, js_err); },
        Err(e) => {
          let c_reason = CString::new(e.reason.as_str())
            .unwrap_or_else(|_| CString::new("Unknown error").unwrap());
          let mut msg: sys::napi_value = std::ptr::null_mut();
          let mut error: sys::napi_value = std::ptr::null_mut();
          unsafe {
            sys::napi_create_string_utf8(
              env,
              c_reason.as_ptr(),
              c_reason.to_bytes().len() as isize,
              &mut msg,
            );
            sys::napi_create_error(env, std::ptr::null_mut(), msg, &mut error);
            sys::napi_reject_deferred(env, deferred, error);
          }
        }
      }) as SettleCallback,
    }
  });

  REGISTRY.with(|r| {
    r.borrow_mut().insert(boxed, deferred);
  });

  Ok(JsPromise(promise))
}


// ---------------------------------------------------------------------------
// Example: a bridged async function exposed to JS
// ---------------------------------------------------------------------------

/// Sleep for `ms` milliseconds using tokio::time (driven by the dedicated
/// reactor thread), then return.  Demonstrates a future polled directly by
/// the Node event loop via the WakerBridge.
#[napi(ts_return_type = "Promise<void>")]
pub fn bridged_sleep(env: Env, ms: u32) -> Result<JsPromise> {
  // println!("bridged_sleep called with {ms} ms");
  let dur = std::time::Duration::from_millis(ms as u64);
  submit_future(&env, async move {
    // println!("Sleeping for {ms} ms...");
    tokio::time::sleep(dur).await;
    // println!("Done sleeping for {ms} ms");
    Ok(())
  })
}
