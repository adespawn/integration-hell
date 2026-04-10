use std::sync::Arc;

use scylla::cluster::metadata::{Column, ColumnKind, Keyspace, MaterializedView, Strategy, Table};
use scylla::frame::response::result::UserDefinedType;

use crate::{
    session::SessionWrapper,
    types::type_wrappers::ComplexType,
    utils::to_napi_obj::{NamedMap, define_rust_to_js_convertible_object},
};

define_rust_to_js_convertible_object!(
    enum TColumnKind
    where
        VariantName: kind,
    {
        Regular = 0,
        Static = 1,
        Clustering = 2,
        PartitionKey = 3,
    }
);

impl From<ColumnKind> for TColumnKind {
    fn from(k: ColumnKind) -> Self {
        match k {
            ColumnKind::Regular => TColumnKind::Regular,
            ColumnKind::Static => TColumnKind::Static,
            ColumnKind::Clustering => TColumnKind::Clustering,
            ColumnKind::PartitionKey => TColumnKind::PartitionKey,
            _ => TColumnKind::Regular,
        }
    }
}

define_rust_to_js_convertible_object!(
    ColumnWrapper {
        typ, cqlType: ComplexType<'static>,
        kind, kind: TColumnKind,
    }
);

impl From<Column> for ColumnWrapper {
    fn from(c: Column) -> Self {
        ColumnWrapper {
            typ: ComplexType::new_owned(c.typ),
            kind: TColumnKind::from(c.kind),
        }
    }
}

define_rust_to_js_convertible_object!(
    TableWrapper {
        columns, columns: NamedMap<String, Column, ColumnWrapper>,
        partition_key, partitionKey: Vec<String>,
        clustering_key, clusteringKey: Vec<String>,
        partitioner, partitioner: Option<String>,
    }
);

impl From<Table> for TableWrapper {
    fn from(t: Table) -> Self {
        TableWrapper {
            columns: NamedMap::new(t.columns),
            partition_key: t.partition_key,
            clustering_key: t.clustering_key,
            partitioner: t.partitioner,
        }
    }
}

#[rustfmt::skip] // fmt splits each field definition into multiple lines
define_rust_to_js_convertible_object!(MaterializedViewWrapper {
    view_metadata, viewMetadata: TableWrapper,
    table_name, tableName: String,
});

impl From<MaterializedView> for MaterializedViewWrapper {
    fn from(v: MaterializedView) -> Self {
        MaterializedViewWrapper {
            view_metadata: v.view_metadata.into(),
            table_name: v.base_table_name,
        }
    }
}

define_rust_to_js_convertible_object!(
    UdtFieldWrapper {
        name, name: String,
        typ, type: ComplexType<'static>,
    }
);

define_rust_to_js_convertible_object!(
    UdtWrapper {
        name, name: String,
        keyspace, keyspace: String,
        fields, fields: Vec<UdtFieldWrapper>,
    }
);

impl From<Arc<UserDefinedType<'static>>> for UdtWrapper {
    fn from(udt: Arc<UserDefinedType<'static>>) -> Self {
        UdtWrapper {
            name: udt.name.to_string(),
            keyspace: udt.keyspace.to_string(),
            fields: udt
                .field_types
                .iter()
                .map(|(name, typ)| UdtFieldWrapper {
                    name: name.to_string(),
                    typ: ComplexType::new_owned(typ.clone()),
                })
                .collect(),
        }
    }
}

define_rust_to_js_convertible_object!(
    enum StrategyWrapper
    where
        VariantName: kind,
    {
        SimpleStrategy {
            replication_factor, replicationFactor: u32,
        } = 0,
        NetworkTopologyStrategy {
            datacenter_repfactors, datacenterRepfactors: NamedMap<String, u32, u32>,
        } = 1,
        LocalStrategy = 2,
        Other {
            name, name: String,
            data, data: NamedMap<String, String, String>,
        } = 3,
    }
);

impl From<Strategy> for StrategyWrapper {
    fn from(s: Strategy) -> Self {
        match s {
            Strategy::SimpleStrategy { replication_factor } => StrategyWrapper::SimpleStrategy {
                replication_factor: replication_factor as u32,
            },
            Strategy::NetworkTopologyStrategy {
                datacenter_repfactors,
            } => StrategyWrapper::NetworkTopologyStrategy {
                datacenter_repfactors: NamedMap::new(
                    datacenter_repfactors
                        .into_iter()
                        .map(|(k, v)| (k, v as u32))
                        .collect(),
                ),
            },
            Strategy::LocalStrategy => StrategyWrapper::LocalStrategy,
            Strategy::Other { name, data } => StrategyWrapper::Other {
                name,
                data: NamedMap::new(data),
            },
            _ => StrategyWrapper::Other {
                name: String::new(),
                data: NamedMap::new(std::collections::HashMap::new()),
            },
        }
    }
}

define_rust_to_js_convertible_object!(
    KeyspaceWrapper {
        strategy, strategy: StrategyWrapper,
        tables, tables: NamedMap<String, Table, TableWrapper>,
        views, views: NamedMap<String, MaterializedView, MaterializedViewWrapper>,
        user_defined_types, userDefinedTypes: NamedMap<String, Arc<UserDefinedType<'static>>, UdtWrapper>,
    }
);

impl From<Keyspace> for KeyspaceWrapper {
    fn from(ks: Keyspace) -> Self {
        KeyspaceWrapper {
            strategy: StrategyWrapper::from(ks.strategy),
            tables: NamedMap::new(ks.tables),
            views: NamedMap::new(ks.views),
            user_defined_types: NamedMap::new(ks.user_defined_types),
        }
    }
}

#[napi]
impl SessionWrapper {
    #[napi]
    pub fn get_all_keyspaces_metadata(&self) -> Vec<KeyspaceWrapper> {
        let cluster_state = self.inner.get_session().get_cluster_state();
        cluster_state
            .keyspaces_iter()
            .map(|(_, ks)| KeyspaceWrapper::from(ks.clone()))
            .collect()
    }

    #[napi]
    pub fn get_filtered_keyspace_metadata(&self, name: String) -> Option<KeyspaceWrapper> {
        let cluster_state = self.inner.get_session().get_cluster_state();
        cluster_state
            .get_keyspace(&name)
            .map(|ks| KeyspaceWrapper::from(ks.clone()))
    }
}
