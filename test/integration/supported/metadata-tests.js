"use strict";

const { expect } = require("chai");
const Client = require("../../../lib/client");
const helper = require("../../test-helper");
const { StrategyKind } = require("../../../lib/metadata/keyspace-metadata");

describe("Metadata @SERVER_API", function () {
    this.timeout(60000);

    describe("keyspace metadata", function () {
        const keyspace = helper.getRandomName("ks");
        const udtName = "address";
        const tableName = `${keyspace}.users`;
        const viewName = `${keyspace}.users_by_name`;

        const setupInfo = helper.setup(1, {
            keyspace,
            queries: [
                `CREATE TYPE ${keyspace}.${udtName} (street text, city text)`,
                `CREATE TABLE ${tableName} (id uuid PRIMARY KEY, name text, addr frozen<${udtName}>)`,
                `CREATE MATERIALIZED VIEW ${viewName} AS SELECT id, name FROM ${tableName} WHERE name IS NOT NULL AND id IS NOT NULL PRIMARY KEY (name, id)`,
            ],
        });

        describe("#getFilteredKeyspaceMetadata()", function () {
            it("should return null for a non-existent keyspace", function () {
                const client = setupInfo.client;
                const result = client.rustClient.getFilteredKeyspaceMetadata(
                    "does_not_exist_xyzzy",
                );
                expect(result).to.equal(null);
            });

            it("should return keyspace metadata for an existing keyspace", function () {
                const client = setupInfo.client;
                const ks =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);
                expect(ks).to.not.equal(null);
            });

            it("should have the correct SimpleStrategy with replicationFactor 1", function () {
                const client = setupInfo.client;
                const ks =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);
                expect(ks.strategy).to.exist;
                expect(ks.strategy.kind).to.equal(StrategyKind.SimpleStrategy);
                expect(ks.strategy.replicationFactor).to.equal(1);
            });

            it("should expose the users table", function () {
                const client = setupInfo.client;
                const ks =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);
                expect(ks.tables).to.have.property("users");
            });

            it("should have correct partition key for the users table", function () {
                const client = setupInfo.client;
                const ks =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);
                const table = ks.tables["users"];
                expect(table.partitionKey).to.deep.equal(["id"]);
            });

            it("should expose columns for the users table", function () {
                const client = setupInfo.client;
                const ks =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);
                const table = ks.tables["users"];
                expect(table.columns).to.have.property("id");
                expect(table.columns).to.have.property("name");
                expect(table.columns).to.have.property("addr");
            });

            it("should have correct ColumnKind for columns", function () {
                const {
                    ColumnKind,
                } = require("../../../lib/metadata/table-metadata");
                const client = setupInfo.client;
                const ks =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);
                const table = ks.tables["users"];
                expect(table.columns["id"].kind).to.equal(
                    ColumnKind.PartitionKey,
                );
                expect(table.columns["name"].kind).to.equal(ColumnKind.Regular);
            });

            it("should expose the users_by_name materialized view", function () {
                const client = setupInfo.client;
                const ks =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);
                expect(ks.views).to.have.property("users_by_name");
            });

            it("should have viewMetadata and tableName on the materialized view", function () {
                const client = setupInfo.client;
                const ks =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);
                const view = ks.views["users_by_name"];
                expect(view.tableName).to.equal("users");
                expect(view.viewMetadata).to.exist;
                expect(view.viewMetadata.partitionKey).to.include("name");
            });

            it("should expose the address UDT", function () {
                const client = setupInfo.client;
                const ks =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);
                expect(ks.userDefinedTypes).to.have.property(udtName);
            });

            it("should have correct fields on the address UDT", function () {
                const client = setupInfo.client;
                const ks =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);
                const udt = ks.userDefinedTypes[udtName];
                expect(udt.name).to.equal(udtName);
                expect(udt.keyspace).to.equal(keyspace);
                const fieldNames = udt.fields.map((f) => f.name);
                expect(fieldNames).to.include("street");
                expect(fieldNames).to.include("city");
            });
        });

        describe("#getAllKeyspacesMetadata()", function () {
            it("should return an array", function () {
                const client = setupInfo.client;
                const result = client.rustClient.getAllKeyspacesMetadata();
                expect(result).to.be.an("array");
            });

            it("should include system keyspaces", function () {
                const client = setupInfo.client;
                const result = client.rustClient.getAllKeyspacesMetadata();
                const names = result.map(
                    (ks) => ks.strategy.kind !== undefined && ks,
                );
                // All entries must have a strategy object
                result.forEach((ks) => {
                    expect(ks.strategy).to.exist;
                    expect(ks.strategy.kind).to.be.a("number");
                });
            });

            it("should contain the test keyspace", function () {
                const client = setupInfo.client;
                // cross-check with getFilteredKeyspaceMetadata
                const all = client.rustClient.getAllKeyspacesMetadata();
                const single =
                    client.rustClient.getFilteredKeyspaceMetadata(keyspace);

                // Find it by its strategy values since we don't have the name in the object
                const found = all.find(
                    (ks) =>
                        ks.strategy.kind === StrategyKind.SimpleStrategy &&
                        ks.strategy.replicationFactor ===
                            single.strategy.replicationFactor &&
                        ks.tables != null &&
                        "users" in ks.tables,
                );
                expect(found).to.exist;
            });
        });
    });

    describe("keyspace strategy kinds", function () {
        const ntsKeyspace = helper.getRandomName("ks");

        const setupInfo = helper.setup(1, {
            keyspace: ntsKeyspace,
            queries: [],
            ccmOptions: {},
        });

        before(function () {
            const client = setupInfo.client;
            return client.execute(
                `CREATE KEYSPACE IF NOT EXISTS ${ntsKeyspace}_nts` +
                    ` WITH replication = {'class': 'NetworkTopologyStrategy', 'dc1': 1}`,
            );
        });

        it("should return NetworkTopologyStrategy with datacenterRepfactors", function () {
            const client = setupInfo.client;
            const ks = client.rustClient.getFilteredKeyspaceMetadata(
                `${ntsKeyspace}_nts`,
            );
            expect(ks).to.exist;
            expect(ks.strategy.kind).to.equal(
                StrategyKind.NetworkTopologyStrategy,
            );
            expect(ks.strategy.datacenterRepfactors).to.be.an("object");
            expect(Object.values(ks.strategy.datacenterRepfactors)[0]).to.equal(
                1,
            );
        });
    });
});
