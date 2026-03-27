"use strict";

function validatePositiveInteger(name, value) {
    if (!Number.isInteger(value) || value <= 0) {
        throw new Error(`${name} must be a positive integer`);
    }
}

function percentile(sortedValues, p) {
    if (sortedValues.length === 0) {
        return 0;
    }

    const index = Math.ceil((p / 100) * sortedValues.length) - 1;
    return sortedValues[Math.max(0, Math.min(index, sortedValues.length - 1))];
}

function nsToMs(value) {
    return value / 1e6;
}

function standardDeviation(values, mean) {
    if (values.length === 0) {
        return 0;
    }

    const variance =
        values.reduce((sum, value) => {
            const diff = value - mean;
            return sum + diff * diff;
        }, 0) / values.length;

    return Math.sqrt(variance);
}

function printLatencyStats(latenciesNs, totalNs, metadata) {
    const sortedLatencies = [...latenciesNs].sort((a, b) => a - b);
    const sumNs = latenciesNs.reduce((sum, value) => sum + value, 0);
    const meanNs = sumNs / latenciesNs.length;
    const stddevNs = standardDeviation(latenciesNs, meanNs);
    const percentilesMs = {};

    for (let p = 5; p < 100; p += 5) {
        percentilesMs[`p${p}Ms`] = nsToMs(percentile(sortedLatencies, p));
    }

    percentilesMs.p98Ms = nsToMs(percentile(sortedLatencies, 98));
    percentilesMs.p99Ms = nsToMs(percentile(sortedLatencies, 99));
    percentilesMs["p99.5Ms"] = nsToMs(percentile(sortedLatencies, 99.5));
    percentilesMs["p99.9Ms"] = nsToMs(percentile(sortedLatencies, 99.9));

    const stats = {
        ...metadata,
        totalMs: nsToMs(totalNs),
        throughput: (latenciesNs.length * 1e9) / totalNs,
        minMs: nsToMs(sortedLatencies[0]),
        meanMs: nsToMs(meanNs),
        stddevMs: nsToMs(stddevNs),
        ...percentilesMs,
        maxMs: nsToMs(sortedLatencies[sortedLatencies.length - 1]),
    };

    console.log(JSON.stringify(stats, null, 2));
}

exports.validatePositiveInteger = validatePositiveInteger;
exports.printLatencyStats = printLatencyStats;
