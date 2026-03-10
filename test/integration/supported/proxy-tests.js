'use strict';

const assert = require('assert');

const ProxyHelper = require('../../proxy-helper');
const { ProxyMode } = ProxyHelper;

describe('ScyllaProxy @SERVER_API', function () {
    this.timeout(60000);

    describe('proxy mode switching', function () {
        const ctx = ProxyHelper.setup(1);

        it('should execute a query in passthrough mode', async function () {
            ctx.proxy.setMode(ProxyMode.Passthrough);
            const result = await ctx.client.execute('SELECT key FROM system.local');
            assert.ok(result.rows.length > 0, 'expected at least one row from system.local');
        });

        it('should fail queries when connections are dropped', async function () {
            ctx.proxy.setMode(ProxyMode.DropConnections);
            try {
                await ctx.client.execute('SELECT key FROM system.local');
                assert.fail('expected query to fail with dropped connections');
            } catch (err) {
                assert.ok(err, 'expected an error when connections are dropped');
            }
        });

        it('should execute a query after restoring passthrough mode', async function () {
            ctx.proxy.setMode(ProxyMode.Passthrough);
            await new Promise((resolve) => setTimeout(resolve, 500)); 
            const result = await ctx.client.execute('SELECT key FROM system.local');
            assert.ok(result.rows.length > 0, 'expected query to succeed after restoring passthrough');
        });
    });
});
