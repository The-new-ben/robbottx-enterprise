import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..'
);

export const fixturePath = path.join(
  repositoryRoot,
  'packages',
  'canonical',
  'fixtures',
  'turtlebot3-waffle-pi-openmanipulator-x.candidate.json'
);

export const snapshotPath = path.join(
  repositoryRoot,
  'wp-content',
  'plugins',
  'robbottx-core',
  'resources',
  'publication',
  'golden-slice.v0.json'
);

const typedIdPatterns = {
  entity: /^RBTX:E:[0-9a-f-]{36}$/,
  revision: /^RBTX:R:[0-9a-f-]{36}$/,
  evidence: /^RBTX:EV:[0-9a-f-]{36}$/,
  assertion: /^RBTX:A:[0-9a-f-]{36}$/,
  edge: /^RBTX:ED:[0-9a-f-]{36}$/,
  configuration: /^RBTX:C:[0-9a-f-]{36}$/,
  bom: /^RBTX:B:[0-9a-f-]{36}$/,
  rule: /^RBTX:BR:[0-9a-f-]{36}$/,
  assessment: /^RBTX:CA:[0-9a-f-]{36}$/,
  snapshot: /^RBTX:S:[0-9a-f-]{36}$/
};

const uuid7Pattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const requiredDimensions = new Set([
  'mechanical_geometry',
  'electrical_power',
  'connector_pinout',
  'protocol_communications',
  'firmware_software_licensing',
  'performance_timing',
  'thermal_environmental',
  'safety_regulatory',
  'lifecycle_supply_region',
  'mission_planetary_environment'
]);

const publicStateLabels = {
  confirmed: 'Confirmed',
  conditional: 'Conditional',
  adapter_required: 'Adapter required',
  version_constrained: 'Version constrained',
  incompatible: 'Incompatible',
  unverified: 'Unverified',
  conflicting_evidence: 'Conflicting evidence',
  engineering_review_required: 'Engineering review required',
  not_applicable: 'Not applicable'
};

const dimensionLabels = {
  mechanical_geometry: 'Mechanical + geometry',
  electrical_power: 'Electrical + power',
  connector_pinout: 'Connector + pinout',
  protocol_communications: 'Protocol + communications',
  firmware_software_licensing: 'Firmware + software + licensing',
  performance_timing: 'Performance + timing',
  thermal_environmental: 'Thermal + environmental',
  safety_regulatory: 'Safety + regulatory',
  lifecycle_supply_region: 'Lifecycle + supply + region',
  mission_planetary_environment: 'Mission + planetary environment'
};

export function stableValue(value) {
  if (Array.isArray(value)) {
    return value.map(stableValue);
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, stableValue(child)])
    );
  }

  return value;
}

export function stableStringify(value, space = 0) {
  return JSON.stringify(stableValue(value), null, space);
}

export function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function assert(condition, message, errors) {
  if (!condition) {
    errors.push(message);
  }
}

function validateTypedId(value, type, errors, context) {
  const pattern = typedIdPatterns[type];
  assert(typeof value === 'string' && pattern.test(value), `${context}: invalid ${type} ID`, errors);
  const uuid = typeof value === 'string' ? value.split(':').at(-1) : '';
  assert(uuid7Pattern.test(uuid), `${context}: ID must contain a UUIDv7`, errors);
}

function uniqueIndex(records, key, errors, context) {
  const index = new Map();

  for (const record of records) {
    const value = record[key];
    assert(!index.has(value), `${context}: duplicate ${key} ${value}`, errors);
    index.set(value, record);
  }

  return index;
}

export function validateDataset(dataset) {
  const errors = [];

  assert(dataset.schema_version === '0.1.0', 'schema_version must be 0.1.0', errors);
  validateTypedId(dataset.dataset_id, 'snapshot', errors, 'dataset');
  assert(['candidate', 'approved', 'superseded', 'withdrawn'].includes(dataset.dataset_status), 'invalid dataset_status', errors);

  for (const field of ['entities', 'revisions', 'labels', 'evidence', 'assertions', 'edges', 'offers', 'assets_3d']) {
    assert(Array.isArray(dataset[field]), `${field} must be an array`, errors);
  }

  if (errors.length > 0) {
    return errors;
  }

  const entityIndex = uniqueIndex(dataset.entities, 'entity_id', errors, 'entities');
  const revisionIndex = uniqueIndex(dataset.revisions, 'revision_id', errors, 'revisions');
  const evidenceIndex = uniqueIndex(dataset.evidence, 'evidence_id', errors, 'evidence');
  uniqueIndex(dataset.assertions, 'assertion_id', errors, 'assertions');
  uniqueIndex(dataset.edges, 'edge_id', errors, 'edges');

  for (const entity of dataset.entities) {
    validateTypedId(entity.entity_id, 'entity', errors, 'entity');
  }

  for (const revision of dataset.revisions) {
    validateTypedId(revision.revision_id, 'revision', errors, 'revision');
    assert(entityIndex.has(revision.entity_id), `revision ${revision.revision_id}: missing entity`, errors);
    assert(typeof revision.fingerprint === 'string' && revision.fingerprint.length >= 8, `revision ${revision.revision_id}: weak fingerprint`, errors);
  }

  for (const label of dataset.labels) {
    assert(entityIndex.has(label.entity_id), `label ${label.text}: missing entity`, errors);
    assert(/^[a-z]{2,3}(-[A-Za-z0-9]+)*$/.test(label.language), `label ${label.text}: invalid BCP-47 language`, errors);
    for (const evidenceId of label.evidence_ids) {
      assert(evidenceIndex.has(evidenceId), `label ${label.text}: missing evidence ${evidenceId}`, errors);
    }
  }

  for (const evidence of dataset.evidence) {
    validateTypedId(evidence.evidence_id, 'evidence', errors, 'evidence');
    assert(/^https:\/\//.test(evidence.url), `evidence ${evidence.evidence_id}: HTTPS URL required`, errors);
    assert(/^[0-9a-f]{64}$/.test(evidence.response_sha256), `evidence ${evidence.evidence_id}: invalid SHA-256`, errors);
    assert(evidence.locator?.length > 0, `evidence ${evidence.evidence_id}: exact locator required`, errors);
  }

  for (const assertion of dataset.assertions) {
    validateTypedId(assertion.assertion_id, 'assertion', errors, 'assertion');
    assert(revisionIndex.has(assertion.subject_revision_id), `assertion ${assertion.assertion_id}: missing subject revision`, errors);
    assert(assertion.evidence_ids.length > 0, `assertion ${assertion.assertion_id}: evidence required`, errors);
    for (const evidenceId of assertion.evidence_ids) {
      assert(evidenceIndex.has(evidenceId), `assertion ${assertion.assertion_id}: missing evidence ${evidenceId}`, errors);
    }
    if (typeof assertion.value.normalized === 'number') {
      assert(Boolean(assertion.value.unit), `assertion ${assertion.assertion_id}: numeric value requires unit`, errors);
    }
    assert(assertion.conditions !== undefined, `assertion ${assertion.assertion_id}: conditions required`, errors);
  }

  for (const edge of dataset.edges) {
    validateTypedId(edge.edge_id, 'edge', errors, 'edge');
    assert(edge.evidence_ids.length > 0, `edge ${edge.edge_id}: evidence required`, errors);
    for (const evidenceId of edge.evidence_ids) {
      assert(evidenceIndex.has(evidenceId), `edge ${edge.edge_id}: missing evidence ${evidenceId}`, errors);
    }
  }

  validateTypedId(dataset.configuration.configuration_id, 'configuration', errors, 'configuration');
  validateTypedId(dataset.bom.bom_id, 'bom', errors, 'BOM');
  assert(dataset.configuration.bom_id === dataset.bom.bom_id, 'configuration and BOM IDs disagree', errors);
  assert(entityIndex.has(dataset.configuration.configuration_entity_id), 'configuration entity is missing', errors);

  const findNumbers = new Set();
  for (const item of dataset.bom.items) {
    assert(!findNumbers.has(item.find_number), `BOM duplicate find number ${item.find_number}`, errors);
    findNumbers.add(item.find_number);
    assert(revisionIndex.has(item.item_revision_id), `BOM item ${item.find_number}: missing revision`, errors);
    assert(item.quantity > 0, `BOM item ${item.find_number}: quantity must be positive`, errors);
    assert(item.evidence_ids.length > 0, `BOM item ${item.find_number}: evidence required`, errors);
  }

  validateTypedId(dataset.compatibility.assessment_id, 'assessment', errors, 'compatibility');
  const seenDimensions = new Set();
  for (const result of dataset.compatibility.results) {
    assert(!seenDimensions.has(result.dimension), `duplicate compatibility dimension ${result.dimension}`, errors);
    seenDimensions.add(result.dimension);
    assert(publicStateLabels[result.state], `invalid compatibility state ${result.state}`, errors);
    if (!['unverified', 'engineering_review_required', 'not_applicable'].includes(result.state)) {
      assert(result.evidence_ids.length > 0, `${result.dimension}: non-unknown result requires evidence`, errors);
    }
    for (const evidenceId of result.evidence_ids) {
      assert(evidenceIndex.has(evidenceId), `${result.dimension}: missing evidence ${evidenceId}`, errors);
    }
  }

  for (const dimension of requiredDimensions) {
    assert(seenDimensions.has(dimension), `missing compatibility dimension ${dimension}`, errors);
  }

  for (const rule of dataset.compatibility.rules) {
    validateTypedId(rule.rule_id, 'rule', errors, 'compatibility rule');
    assert(rule.test_cases.length >= 3, `rule ${rule.rule_id}: positive, negative, and boundary tests required`, errors);
  }

  const blocking = dataset.publication.blockers.filter(({ severity }) => severity === 'blocking');
  if (blocking.length > 0) {
    assert(dataset.publication.eligible === false, 'blocking publication issues require eligible=false', errors);
    assert(dataset.publication.indexability === 'noindex', 'ineligible publication must be noindex', errors);
  }

  if (dataset.publication.eligible) {
    assert(dataset.dataset_status === 'approved', 'eligible publication requires approved dataset', errors);
    assert(dataset.compatibility.overall_state !== 'engineering_review_required', 'eligible publication cannot require engineering review', errors);
  }

  const raw = stableStringify(dataset).toLowerCase();
  for (const forbidden of ['legacy-catalog', 'old-catalog', 'robot-catalog', 'catalog-images']) {
    assert(!raw.includes(forbidden), `forbidden retired-catalog marker found: ${forbidden}`, errors);
  }

  return errors;
}

function labelForEntity(dataset, entityId) {
  return dataset.labels.find(
    (label) => label.entity_id === entityId && label.language === 'en'
  )?.text;
}

function sourceSummaries(dataset, evidenceIds) {
  const wanted = new Set(evidenceIds);
  return dataset.evidence
    .filter(({ evidence_id: evidenceId }) => wanted.has(evidenceId))
    .map((evidence) => ({
      evidence_id: evidence.evidence_id,
      publisher: evidence.publisher,
      url: evidence.url,
      locator: evidence.locator,
      retrieved_at: evidence.retrieved_at,
      response_sha256: evidence.response_sha256,
      evidence_class: evidence.evidence_class
    }));
}

function formattedAssertion(assertion) {
  const value = assertion.value;

  if (value.qualifier === 'less_than') {
    return `< ${value.normalized} ${value.unit}`;
  }

  if (value.qualifier === 'range') {
    return `${value.minimum}-${value.maximum} ${value.unit}`;
  }

  if (value.unit === 'count') {
    return String(value.normalized);
  }

  if (value.unit) {
    return `${value.normalized} ${value.unit}`;
  }

  return String(value.raw);
}

export function buildSnapshot(dataset) {
  const errors = validateDataset(dataset);
  if (errors.length > 0) {
    throw new Error(`Canonical dataset validation failed:\n- ${errors.join('\n- ')}`);
  }

  const configurationEntityId = dataset.configuration.configuration_entity_id;
  const publicAssertionPredicates = new Set([
    'electrical.input_voltage',
    'kinematics.degrees_of_freedom',
    'performance.payload',
    'performance.repeatability',
    'physical.mass',
    'geometry.reach',
    'geometry.gripper_stroke',
    'geometry.envelope',
    'software.tested_baseline'
  ]);

  const specificationLabels = {
    'electrical.input_voltage': 'Arm input voltage',
    'kinematics.degrees_of_freedom': 'Arm degrees of freedom',
    'performance.payload': 'Arm payload (manufacturer claim)',
    'performance.repeatability': 'Arm repeatability (manufacturer claim)',
    'physical.mass': 'Arm summary mass',
    'geometry.reach': 'Arm reach',
    'geometry.gripper_stroke': 'Gripper stroke',
    'geometry.envelope': 'Base envelope',
    'software.tested_baseline': 'Documented test baseline'
  };

  const specifications = dataset.assertions
    .filter(({ predicate }) => publicAssertionPredicates.has(predicate))
    .map((assertion) => ({
      label: specificationLabels[assertion.predicate],
      value: formattedAssertion(assertion),
      predicate: assertion.predicate,
      assertion_id: assertion.assertion_id,
      claim_class: assertion.claim_class,
      conditions: assertion.conditions,
      evidence_ids: assertion.evidence_ids
    }));

  const evidenceIds = new Set();
  for (const assertion of dataset.assertions) {
    assertion.evidence_ids.forEach((id) => evidenceIds.add(id));
  }
  for (const result of dataset.compatibility.results) {
    result.evidence_ids.forEach((id) => evidenceIds.add(id));
  }

  const payload = {
    identity: {
      canonical_id: configurationEntityId,
      configuration_revision_id: dataset.configuration.configuration_id,
      name: labelForEntity(dataset, configurationEntityId),
      manufacturer: 'ROBOTIS',
      category: 'Mobile manipulator configuration',
      version: dataset.configuration.version
    },
    status: {
      label: 'Research candidate',
      publication_eligible: dataset.publication.eligible,
      indexability: dataset.publication.indexability,
      overall_compatibility: dataset.compatibility.overall_state,
      verified_on: dataset.compatibility.evaluated_at.slice(0, 10)
    },
    summary:
      'An evidence-backed research preview of a TurtleBot3 Waffle Pi base with an OpenMANIPULATOR-X. Manufacturer documentation supports the relationship, but exact revision applicability and multiple engineering dimensions remain open.',
    evidence_summary: {
      primary_sources: dataset.evidence.length,
      public_language: dataset.publication.public_language,
      assertion_count: dataset.assertions.length,
      relationship_count: dataset.edges.length,
      unsupported_compatibility_passes: 0
    },
    graph_path: [
      'Research mission',
      'Mobile manipulator configuration',
      'TurtleBot3 Waffle Pi',
      'OpenMANIPULATOR-X',
      'OpenCR + Raspberry Pi 4',
      'ROS 2 Humble on Ubuntu 22.04',
      'Primary evidence'
    ],
    specifications,
    compatibility: dataset.compatibility.results.map((result) => ({
      dimension: result.dimension,
      label: dimensionLabels[result.dimension] ?? result.dimension,
      state: result.state,
      state_label: publicStateLabels[result.state],
      basis: result.basis,
      conditions: result.conditions,
      evidence_ids: result.evidence_ids
    })),
    sources: sourceSummaries(dataset, [...evidenceIds]),
    blockers: dataset.publication.blockers,
    disclosures: [
      'Manufacturer-published facts are not RobbottX physical test results.',
      'Unknown compatibility never passes.',
      'No price, stock, certification, safety rating, or planetary qualification is claimed.',
      'The retired catalog CSV and image collection were not used.'
    ]
  };

  return {
    format_version: '0.1.0',
    snapshot_id: 'RBTX:S:019f8f7d-996f-7937-a365-c1dd812cb0db',
    generated_at: dataset.created_at,
    source_dataset_id: dataset.dataset_id,
    source_dataset_sha256: sha256(stableStringify(dataset)),
    payload_sha256: sha256(stableStringify(payload)),
    projection_state: dataset.publication.eligible ? 'approved' : 'candidate',
    payload
  };
}

export async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, 'utf8'));
}

export async function writeJson(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, `${stableStringify(value, 2)}\n`, 'utf8');
}
