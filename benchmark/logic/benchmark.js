// Single entry point for all benchmarks.
// This file takes the name of the benchmark, including driver name, step count and concurrency level
// and runs the corresponding benchmark logic, loaded at runtime.

"use strict";
const { exit } = require("process");
const utils = require("./utils");

const defaultConcurrencyLevel = 100;

const driverName = process.argv[2];
const benchmarkName = process.argv[3];
// Each individual benchmark has a default step count defined.
// See the explanation in config.yml for more details.
const stepCount = process.argv[4] !== "default" ? parseInt(process.argv[4], 10) : undefined;
const concurrencyLevel = process.argv[5] !== "default" ? parseInt(process.argv[5], 10) : defaultConcurrencyLevel;

if (!driverName || !benchmarkName) {
    console.error("Usage: node benchmark.js <driver> <benchmark-name> [step-count] [concurrency]");
    exit(1);
}

const cassandra = require(driverName);
const client = new cassandra.Client(utils.getClientArgs());

const benchmark = require(`./${benchmarkName}`);
benchmark(cassandra, client, stepCount, concurrencyLevel);
