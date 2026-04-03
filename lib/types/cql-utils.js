"use strict";

const rust = require("../../index");
const _Encoder = require("../encoder");

/**
 * @typedef {Object} DataTypeOptions
 * @property {boolean} [frozen]
 * @property {boolean} [reversed]
 */

/**
 * @typedef {Object} UdtFieldInfo
 * @property {string} name
 * @property {DataTypeInfo} type
 */

/**
 * @typedef {Object} UdtTypeInfo
 * @property {string} name
 * @property {string} [keyspace]
 * @property {Array.<UdtFieldInfo>} fields
 */

/**
 * @typedef {Object} DataTypeInfo
 * @property {number} code
 * @property {null|string|DataTypeInfo|Array.<DataTypeInfo>|UdtTypeInfo} info
 * @property {DataTypeOptions} [options]
 * @property {string} [customTypeName]
 */


/**
 * @param {Array<rust.ComplexType | null>} expectedTypes List of expected types.
 * @param {Array<any>} params
 * @param {_Encoder} encoder
 * @returns {Array<rust.ComplexType|any>} Returns: [] for null values, [undefined] for unset values
 * and [rust.ComplexType, any] for all other values.
 * @throws ResponseError when received different amount of parameters than expected
 */
function encodeParams(expectedTypes, params, encoder) {
    if (expectedTypes.length == 0 && !params) return [];
    let res = [];
    for (let i = 0; i < params.length; i++) {
        let tmp = encoder.encode(params[i], expectedTypes[i]);
        res.push(tmp);
    }
    return res;
}

/**
 * Convert rust ComplexType into a DataTypeInfo descriptor.
 * @param {rust.ComplexType} type
 * @returns {DataTypeInfo}
 */
function convertComplexType(type) {
    try {
        /**
         * @type {rust.CqlType}
         */
        let baseType = type.baseType;
        const code = baseType.valueOf();
        switch (baseType) {
            case rust.CqlType.List:
            case rust.CqlType.Set:
                return { code, info: convertComplexType(type.subtype1) };
            case rust.CqlType.Map:
                return { code, info: [
                    convertComplexType(type.subtype1),
                    convertComplexType(type.subtype2),
                ] };
            case rust.CqlType.Vector:
                return {
                    code: 0x0000, // dataTypes.custom
                    info: [convertComplexType(type.subtype1), type.dimensions],
                    customTypeName: "vector",
                };
            case rust.CqlType.UserDefinedType:
                return { code, info: {
                    name: type.name,
                    fields: type.udt_types.map((typ, index) => ({
                        name: type.udt_name[index],
                        type: convertComplexType(typ),
                    })),
                } };
            case rust.CqlType.Tuple:
                return {
                    code,
                    info: type.subtypes.map((typ) => convertComplexType(typ)),
                };
            default:
                return { code, info: null };
        }
    } catch (e) {
        // In this function we do not call other functions, so any error that we may catch here,
        // is due to unexpected structure of ComplexType received from rust driver.
        // However, this should never happen, as any valid ColumnType in rust will generate a valid converted type.
        throw new Error(
            `Error converting ComplexType: ${e.message}. This is likely due to a bug in the driver.`,
        );
    }
}

module.exports.encodeParams = encodeParams;
module.exports.convertComplexType = convertComplexType;
