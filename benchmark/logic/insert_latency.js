"use strict";

const async = require("async");
const { exit } = require("process");

// Possible values of argv[2] (driver) are scylladb-driver-alpha and cassandra-driver.
const cassandra = require(process.argv[2]);
const latencyUtils = require("./latency_utils");
const utils = require("./utils");

const client = new cassandra.Client(utils.getClientArgs());
const iterCnt = parseInt(process.argv[3], 10);
const concurrency = parseInt(process.argv[4] || "1", 10);

const query = "INSERT INTO benchmarks.basic (id, val) VALUES (?, ?)";

function validateArgs() {
    latencyUtils.validatePositiveInteger("Number of queries", iterCnt);
    latencyUtils.validatePositiveInteger("Concurrency", concurrency);
}

function printStats(latenciesNs, totalNs) {
    latencyUtils.printLatencyStats(latenciesNs, totalNs, {
        queries: iterCnt,
        concurrency,
    });
}

async function runBenchmark(next) {
    const latenciesNs = new Array(iterCnt);
    let currentIndex = 0;
    const workerCount = Math.min(concurrency, iterCnt);
    const startTotal = process.hrtime.bigint();

    try {
        await Promise.all(
            Array.from({ length: workerCount }, async () => {
                while (true) {
                    const index = currentIndex;
                    currentIndex += 1;

                    if (index >= iterCnt) {
                        return;
                    }

                    const id = cassandra.types.Uuid.random();
                    const start = process.hrtime.bigint();
                    await client.execute(query, [id, 100], { prepare: true });
                    const end = process.hrtime.bigint();
                    latenciesNs[index] = Number(end - start);
                }
            }),
        );
    } catch (err) {
        return next(err);
    }

    const endTotal = process.hrtime.bigint();
    printStats(latenciesNs, Number(endTotal - startTotal));
    next();
}

validateArgs();

async.series(
    [
        function initialize(next) {
            utils.prepareDatabase(client, utils.tableSchemaBasic, next);
        },
        runBenchmark,
        async function test(next) {
            utils.checkRowCount(client, iterCnt, next);
        },
        function done() {
            exit(0);
        },
    ],
    utils.onError,
);
