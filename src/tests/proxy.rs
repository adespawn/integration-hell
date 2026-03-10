use std::sync::Mutex;

use scylla_proxy::{Condition, Node, Proxy, Reaction, RequestReaction, RequestRule, RunningProxy, ShardAwareness};

use crate::{errors::{JsResult, make_js_error}, types::type_helpers::SocketAddrWrapper};

/// Controls how the proxy handles incoming requests.
#[napi]
pub enum ProxyMode {
    /// Forward all requests to the real node unchanged (noop rule).
    Passthrough,
    /// Drop the TCP connection on every incoming request.
    DropConnections,
}

/// A handle to a running ScyllaDB proxy that can be controlled from JavaScript tests.
///
/// The proxy sits between the driver and a real Scylla/Cassandra node, and allows
/// tests to intercept, modify or drop connections and frames.
///
/// # Example (JavaScript)
/// ```js
/// const proxy = await ScyllaProxyWrapper.start('127.0.0.1:9042', '127.0.0.2:9042');
/// proxy.setMode(ProxyMode.DropConnections); // make all traffic fail
/// proxy.setMode(ProxyMode.Passthrough);     // restore pass-through behaviour
/// await proxy.finish();                     // shut down and clean up
/// ```
#[napi]
pub struct ScyllaProxyWrapper {
    /// The running proxy handle, held in a `Mutex<Option<…>>` so that:
    ///   - the struct is `Sync` (required by napi-rs, which wraps classes in `Arc<T>`), and
    ///   - `finish()` can *consume* the inner `RunningProxy` via `Option::take()` without
    ///     requiring exclusive / consuming ownership of `self`.
    inner: Mutex<Option<RunningProxy>>,
    /// The addresses the proxy listens on, one per node.
    proxy_addrs: Vec<std::net::SocketAddr>,
}

#[napi]
impl ScyllaProxyWrapper {
    /// Start a proxy forwarding traffic for one or more nodes.
    /// `real_addrs[i]` is the actual node address; `proxy_addrs[i]` is where the proxy will listen.
    #[napi]
    pub async fn start(real_addrs: Vec<SocketAddrWrapper>, proxy_addrs: Vec<SocketAddrWrapper>) -> JsResult<ScyllaProxyWrapper> {
        if real_addrs.len() != proxy_addrs.len() {
            return JsResult::NapiError(make_js_error(
                "real_addrs and proxy_addrs must have the same length",
            ));
        }
        if real_addrs.is_empty() {
            return JsResult::NapiError(make_js_error("at least one node must be provided"));
        }

        let (nodes, proxy_sock_addrs): (Vec<Node>, Vec<std::net::SocketAddr>) = real_addrs
            .into_iter()
            .zip(proxy_addrs.into_iter())
            .map(|(real, proxy)| {
                let proxy_sock = proxy.into_inner();
                (
                    Node::new(real.into_inner(), proxy_sock, ShardAwareness::Unaware, None, None),
                    proxy_sock,
                )
            })
            .unzip();

        let proxy = Proxy::new(nodes);

        match proxy.run().await {
            Ok(running) => JsResult::Ok(ScyllaProxyWrapper {
                inner: Mutex::new(Some(running)),
                proxy_addrs: proxy_sock_addrs,
            }),
            Err(e) => JsResult::NapiError(make_js_error(format!("Failed to start proxy: {e}"))),
        }
    }

    /// The addresses the proxy nodes are listening on, as `"ip:port"` strings.
    /// Pass these to your `Client` / session constructor instead of the real node addresses.
    #[napi(getter)]
    pub fn proxy_addresses(&self) -> Vec<String> {
        self.proxy_addrs.iter().map(|a| a.to_string()).collect()
    }

    /// Set the operating mode for all nodes in this proxy.
    #[napi]
    pub fn set_mode(&self, mode: ProxyMode) -> JsResult<()> {
        let mut guard = match self.inner.lock() {
            Ok(g) => g,
            Err(_) => return JsResult::NapiError(make_js_error("Proxy mutex was poisoned")),
        };
        let running = match guard.as_mut() {
            Some(r) => r,
            None => return JsResult::NapiError(make_js_error("Proxy has already been stopped")),
        };
        let rule = match mode {
            ProxyMode::Passthrough => RequestRule(Condition::True, RequestReaction::noop()),
            ProxyMode::DropConnections => {
                RequestRule(Condition::True, RequestReaction::drop_connection())
            }
        };
        for node in &mut running.running_nodes {
            node.change_request_rules(Some(vec![rule.clone()]));
        }
        JsResult::Ok(())
    }

    /// Shut down the proxy gracefully.  All in-flight connections are closed and the
    /// listening socket is released.  Calling any other method after `finish()` will
    /// return an error.
    #[napi]
    pub async fn finish(&self) -> JsResult<()> {
        // Take the RunningProxy out of the Option so we can call the consuming finish().
        let running: RunningProxy = {
            let mut guard = match self.inner.lock() {
                Ok(g) => g,
                Err(_) => return JsResult::NapiError(make_js_error("Proxy mutex was poisoned")),
            };
            match guard.take() {
                Some(r) => r,
                None => return JsResult::NapiError(make_js_error("Proxy has already been stopped")),
            }
        };

        match running.finish().await {
            Ok(()) => JsResult::Ok(()),
            Err(e) => JsResult::NapiError(make_js_error(format!("Proxy error on finish: {e}"))),
        }
    }
}
