'use strict';

/**
 * JS wrapper around the native `ScyllaProxyWrapper` napi-rs binding.
 *
 * Usage — bare proxy (single node):
 *   const proxy = await ProxyHelper.start([{ address: '127.0.0.1', port: 9042 }], [{ address: '127.0.100.1', port: 9042 }]);
 *
 * Usage — full CCM + client setup (mirrors helper.setup()):
 *   const ctx = ProxyHelper.setup(1, { queries: ['CREATE TABLE …'] });
 *   // ctx.client, ctx.keyspace, ctx.proxy are available inside it() blocks
 */

const { ScyllaProxyWrapper, ProxyMode } = require('../index');
const helper = require('./test-helper');
const Client = require('../lib/client');
const utils = require('../lib/utils');

class ProxyHelper {
    constructor(nativeWrapper) {
        this._proxy = nativeWrapper;
    }

    /**
     * Start a proxy without CCM / client management. Proxy starts in pass-through mode.
     * @param {Array<{ address: string, port: number }>} realAddrs
     * @param {Array<{ address: string, port: number }>} proxyAddrs
     * @returns {Promise<ProxyHelper>}
     */
    static async start(realAddrs, proxyAddrs) {
        const wrapper = await ScyllaProxyWrapper.start(realAddrs, proxyAddrs);
        return new ProxyHelper(wrapper);
    }

    /**
     * Creates a ccm cluster, initializes a Client instance the before() and after() hooks
     *
     * @param {number} nodeLength A number representing the amount of nodes in a cluster. 
     * Cannot configure multiple DCs when running with a proxy.
     * @param {Object} [options]
     * @param {Object} [options.ccmOptions]
     * @param {Boolean} [options.initClient] Determines whether to create a Client instance.
     * @param {Object} [options.clientOptions] The options to use to initialize the client.
     * @param {String} [options.keyspace] Name of the keyspace to create.
     * @param {Number} [options.replicationFactor] Keyspace replication factor.
     * @param {Array<String>} [options.queries] Queries to run after client creation.
     * @param {Boolean} [options.removeClusterAfter=true] Determines whether ccm remove should be called on after().
     * @param {boolean} [options.removeClusterAfter=true]
     * @returns {{ client: Client?, keyspace: string?, proxy: ProxyHelper? }}
     */
    static setup(nodeLength, options) {
        options = options || utils.emptyObject;

        const ctx = { client: undefined, keyspace: undefined, proxy: undefined };

        const count = nodeLength || 1;
        before(helper.ccmHelper.start(count, options.ccmOptions));

        const realSockets = [];
        const proxySockets = [];
        for (let i = 1; i <= count; i++) {
            const realAddr = helper.ipPrefix + i;
            const proxyAddr = helper.proxyIpPrefix + i;
            realSockets.push({ address: realAddr, port: 9042 });
            proxySockets.push({ address: proxyAddr, port: 9042 });
        }

        before(async () => {
            ctx.proxy = await ProxyHelper.start(realSockets, proxySockets);
        });

        const initClient = options.initClient !== false;

        if (initClient) {
            before(() => {
                const proxyIps = proxySockets.map(s => s.address);
                ctx.client = new Client(
                    utils.extend({}, options.clientOptions, helper.baseOptions, {
                        contactPoints: proxyIps,
                    }),
                );
            });

            before(() => ctx.client.connect());

            before(() => {
                ctx.keyspace = options.keyspace || helper.getRandomName('ks');
                return ctx.client.execute(
                    helper.createKeyspaceCql(ctx.keyspace, options.replicationFactor),
                );
            });

            before(() => ctx.client.execute('USE ' + ctx.keyspace));

            if (options.queries) {
                before(async () => {
                    for (const q of options.queries) {
                        await ctx.client.execute(q);
                    }
                });
            }

            after(() => ctx.client.shutdown());
        }

        after(async () => ctx.proxy && ctx.proxy.finish());

        if (options.removeClusterAfter !== false) {
            after(helper.ccmHelper.remove);
        }

        return ctx;
    }

    /** All proxy listen addresses as `"ip:port"` strings. @type {string[]} */
    get proxyAddresses() {
        return this._proxy.proxyAddresses;
    }

    setMode(mode) {
        this._proxy.setMode(mode);
    }

    /** Shut down the proxy gracefully. @returns {Promise<void>} */
    async finish() {
        await this._proxy.finish();
    }
}

module.exports = ProxyHelper;
module.exports.ProxyMode = ProxyMode;
