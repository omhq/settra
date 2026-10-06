// Run in the configured Cube image (also included in make test):
// docker compose exec -T cube node - < backend/tests/integration/relationship_sql.cjs
// Compile only in memory; no runtime models or source data are changed.
const assert = require("node:assert/strict");
const { compile, PostgresQuery } = require("@cubejs-backend/schema-compiler");

async function main() {
  const ordersName = "collection_1_0123456789abcdef";
  const key = "customer_business_identifier_with_a_v_4384181bc9";
  const similarKey = key.slice(0, -5) + "abcde";
  const measure = "m".repeat(46) + "B";
  const sqlAlias = "co_4384181bc9";
  const physicalKey =
    "customer_business_identifier_with_a_very_long_column_name";
  const yaml = [
    "cubes:",
    "  - name: " + ordersName,
    "    sql_alias: " + sqlAlias,
    '    sql_table: \'"fixture"."orders"\'',
    "    joins:",
    "      - name: Customers",
    "        relationship: many_to_one",
    '        sql: "{CUBE.' + key + '} = {Customers.id}"',
    "    dimensions:",
    "      - name: order_id",
    "        sql: '\"order_id\"'",
    "        type: string",
    "        primary_key: true",
    "      - name: " + key,
    "        sql: '\"" + physicalKey + "\"'",
    "        type: string",
    "      - name: " + similarKey,
    "        sql: '\"other_customer_key\"'",
    "        type: string",
    "    measures:",
    "      - name: " + measure,
    "        type: count",
    "  - name: Customers",
    '    sql_table: \'"fixture"."customers"\'',
    "    dimensions:",
    "      - name: id",
    "        sql: '{CUBE.key_alias}'",
    "        type: string",
    "        primary_key: true",
    "      - name: key_alias",
    '        sql: \'{CUBE}."CRM Customer ""ID"""\'',
    "        type: string",
    "      - name: customer_name",
    "        sql: '\"customer_name\"'",
    "        type: string",
  ].join("\n");
  const repository = {
    dataSchemaFiles: async () => [
      { fileName: "relationships.yaml", content: yaml },
    ],
  };
  const compilers = await compile(repository, { standalone: true });
  const members = [
    ordersName + "." + key,
    ordersName + "." + similarKey,
    ordersName + "." + measure,
    "Customers.customer_name",
  ];
  const query = new PostgresQuery(compilers, {
    dimensions: [members[0], members[1], members[3]],
    measures: [members[2]],
    timezone: "UTC",
    rowLimit: 5,
  });
  const [sql] = query.buildSqlAndParams();
  assert.match(
    sql,
    /ON\s+.*"customer_business_identifier_with_a_very_long_column_name"\s*=\s*.*"CRM Customer ""ID"""/i,
  );
  assert.ok(!sql.includes(".customer_business_identifier_with_a_v_4384181bc9"));
  assert.ok(!/\bON\b[^\n]*\."id"/i.test(sql));
  const aliases = members.map((member) => query.aliasName(member));
  for (const alias of aliases) {
    assert.ok(Buffer.byteLength(alias, "utf8") <= 63, alias);
    assert.ok(sql.includes(' "' + alias + '"'), alias);
  }
  assert.equal(new Set(aliases).size, members.length);
  assert.equal(Buffer.byteLength(aliases[0], "utf8"), 63);
  assert.equal(Buffer.byteLength(aliases[2], "utf8"), 63);

  const matchingKeyYaml = [
    "cubes:",
    "  - name: SameKeyOrders",
    '    sql_table: \'"fixture"."same_key_orders"\'',
    "    joins:",
    "      - name: SameKeyCustomers",
    "        relationship: many_to_one",
    '        sql: "{CUBE.customer_id} = {SameKeyCustomers.customer_id}"',
    "    dimensions:",
    "      - name: order_id",
    "        sql: '{CUBE}.\"order_id\"'",
    "        type: string",
    "        primary_key: true",
    "      - name: customer_id",
    "        sql: '{CUBE}.\"customer_id\"'",
    "        type: string",
    "    measures:",
    "      - name: row_count",
    "        type: count",
    "  - name: SameKeyCustomers",
    '    sql_table: \'"fixture"."same_key_customers"\'',
    "    dimensions:",
    "      - name: customer_id",
    "        sql: '{CUBE}.\"customer_id\"'",
    "        type: string",
    "        primary_key: true",
    "      - name: customer_name",
    "        sql: '{CUBE}.\"customer_name\"'",
    "        type: string",
  ].join("\n");
  const matchingKeyCompilers = await compile(
    {
      dataSchemaFiles: async () => [
        { fileName: "matching-keys.yaml", content: matchingKeyYaml },
      ],
    },
    {standalone: true},
  );
  const matchingKeyQuery = new PostgresQuery(matchingKeyCompilers, {
    dimensions: ["SameKeyCustomers.customer_name"],
    measures: ["SameKeyOrders.row_count"],
    timezone: "UTC",
    rowLimit: 5,
  });
  const [matchingKeySql] = matchingKeyQuery.buildSqlAndParams();
  const matchingKeyAliases = [
    ...matchingKeySql.matchAll(/"([^"]+)"\."customer_id"/g),
  ].map((match) => match[1]);
  assert.equal(matchingKeyAliases.length, 2);
  assert.equal(new Set(matchingKeyAliases).size, 2);

  // An unbudgeted alias loses the distinguishing key suffixes.
  const unbudgetedCompilers = await compile(
    {
      dataSchemaFiles: async () => [
        {
          fileName: "unbudgeted.yaml",
          content: yaml.replace(sqlAlias, "c_0123456789abcdef"),
        },
      ],
    },
    { standalone: true },
  );
  const unbudgeted = new PostgresQuery(unbudgetedCompilers, {
    dimensions: [members[0], members[1]],
    timezone: "UTC",
  });
  const unbudgetedAliases = [members[0], members[1]].map((member) =>
    unbudgeted.aliasName(member),
  );
  assert.equal(unbudgetedAliases[0].length, 68);
  assert.equal(
    unbudgetedAliases[0].slice(0, 63),
    unbudgetedAliases[1].slice(0, 63),
  );
  console.log(
    "Cube resolves relationship keys correctly and preserves distinct PostgreSQL aliases within 63 bytes.",
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
