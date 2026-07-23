<?php

declare(strict_types=1);

if (! defined('ABSPATH')) {
    exit;
}

return json_decode(
    <<<'ROBBOTTX_RECORD'
{
  "format_version": "0.1.0",
  "generated_at": "2026-07-23T17:15:36.522Z",
  "payload": {
    "compatibility": [
      {
        "basis": "Manufacturer compatibility text names Waffle, while the assembly document labels Waffle Pi. Exact variant applicability is unclear.",
        "conditions": "Confirm the base and arm revisions, mounting hardware, LiDAR position, and stability limits.",
        "dimension": "mechanical_geometry",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9592-701a-8bcc-b11e42d541ae"
        ],
        "label": "Mechanical + geometry",
        "state": "conflicting_evidence",
        "state_label": "Source conflict"
      },
      {
        "basis": "OpenMANIPULATOR-X is specified for 12 V. A complete system power budget and protection scheme are not documented in the reviewed sources.",
        "conditions": "Confirm connectors, cable limits, protection, peak current, and transient behavior for the exact hardware revisions.",
        "dimension": "electrical_power",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e"
        ],
        "label": "Electrical + power",
        "state": "unverified",
        "state_label": "Not confirmed"
      },
      {
        "basis": "The reviewed documents do not provide a complete connector and pinout matrix for this configuration.",
        "conditions": "Confirm the harness, connector orientation, pinout, and interface documentation before assembly.",
        "dimension": "connector_pinout",
        "evidence_ids": [],
        "label": "Connector + pinout",
        "state": "unverified",
        "state_label": "Not confirmed"
      },
      {
        "basis": "ROBOTIS specifies a TTL multidrop bus and lists OpenCR as a controller option.",
        "conditions": "Match device IDs, baud rate, connector, controller firmware, and network topology.",
        "dimension": "protocol_communications",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e"
        ],
        "label": "Protocol + communications",
        "state": "conditional",
        "state_label": "Conditions apply"
      },
      {
        "basis": "The reviewed instructions use Ubuntu 22.04 and ROS 2 Humble. Official repository releases are recorded in the source documents.",
        "conditions": "Use a tested combination of package versions, firmware, operating system updates, dependencies, and configuration.",
        "dimension": "firmware_software_licensing",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9592-701a-8bcc-b11e42d541ae",
          "RBTX:EV:019f8f7d-9595-7cec-b493-54210abe02a5",
          "RBTX:EV:019f8f7d-9596-7554-8882-fbaa2a9beb2a"
        ],
        "label": "Firmware + software + licensing",
        "state": "version_constrained",
        "state_label": "Version specific"
      },
      {
        "basis": "Component specifications are available. Integrated reach, payload, base stability, duty cycle, latency, and task envelope have not been validated as a system.",
        "conditions": "Validate the intended task with calculations, simulation, and physical testing.",
        "dimension": "performance_timing",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e"
        ],
        "label": "Performance + timing",
        "state": "engineering_review_required",
        "state_label": "Requires validation"
      },
      {
        "basis": "The reviewed sources do not state an environmental rating for the complete configuration.",
        "conditions": "Confirm operating temperature, humidity, ingress protection, duty cycle, ventilation, and installation conditions.",
        "dimension": "thermal_environmental",
        "evidence_ids": [],
        "label": "Thermal + environmental",
        "state": "unverified",
        "state_label": "Not confirmed"
      },
      {
        "basis": "The reviewed sources do not provide a system-level risk assessment, protective functions, emergency stop design, or certification scope for this configuration.",
        "conditions": "Perform an application-specific risk assessment and verify all required protective measures.",
        "dimension": "safety_regulatory",
        "evidence_ids": [],
        "label": "Safety + regulatory",
        "state": "engineering_review_required",
        "state_label": "Requires validation"
      },
      {
        "basis": "Supplier, exact SKU, regional availability, lifecycle, warranty, and lead time are not listed for this configuration.",
        "conditions": "Verify current commercial information with an authorized supplier for the target region.",
        "dimension": "lifecycle_supply_region",
        "evidence_ids": [],
        "label": "Lifecycle + supply + region",
        "state": "unverified",
        "state_label": "Not confirmed"
      },
      {
        "basis": "This configuration has no stated qualification for space or planetary use.",
        "conditions": "Space and planetary applications require separate environmental, radiation, contamination, autonomy, communications, and serviceability validation.",
        "dimension": "mission_planetary_environment",
        "evidence_ids": [],
        "label": "Mission + planetary environment",
        "state": "not_applicable",
        "state_label": "Not applicable"
      }
    ],
    "disclosures": [
      "Specifications are based on manufacturer documents. They are not RobbottX physical test results.",
      "Compatibility states apply only to the cited versions and conditions.",
      "Price, stock, warranty, certification, and regional availability must be verified with the relevant supplier."
    ],
    "evidence_summary": {
      "assertion_count": 13,
      "primary_sources": 5,
      "relationship_count": 6
    },
    "identity": {
      "canonical_id": "RBTX:E:019f8f7d-9588-7709-b78b-a1b135c09915",
      "category": "Mobile manipulator configuration",
      "configuration_revision_id": "RBTX:C:019f8f7d-9968-784f-a650-52695f2f6dbb",
      "manufacturer": "ROBOTIS",
      "name": "TurtleBot3 Waffle Pi + OpenMANIPULATOR-X"
    },
    "sources": [
      {
        "evidence_class": "manufacturer_primary",
        "evidence_id": "RBTX:EV:019f8f7d-9592-701a-8bcc-b11e42d541ae",
        "locator": "Manipulation > TurtleBot3 with OpenMANIPULATOR; Hardware Assembly; ROS 2 note",
        "publisher": "ROBOTIS",
        "response_sha256": "d0f255f3376c2dec8bb938d529824053c018f3105085ba1495c06a07dc6e77f5",
        "retrieved_at": "2026-07-23T15:00:00Z",
        "url": "https://emanual.robotis.com/docs/en/platform/turtlebot3/manipulation/"
      },
      {
        "evidence_class": "manufacturer_primary",
        "evidence_id": "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e",
        "locator": "Specification > Hardware Specification table",
        "publisher": "ROBOTIS",
        "response_sha256": "2513bc1bb2069fff8fd8ab770b28b63fb3c5b1905cfec59fbf386f991d007cf1",
        "retrieved_at": "2026-07-23T15:00:00Z",
        "url": "https://emanual.robotis.com/docs/en/platform/openmanipulator_x/specification/"
      },
      {
        "evidence_class": "manufacturer_primary",
        "evidence_id": "RBTX:EV:019f8f7d-9594-7e39-8a42-80cccc977f82",
        "locator": "Features > Hardware Specification table > Waffle Pi",
        "publisher": "ROBOTIS",
        "response_sha256": "66332579829aa5ac60b88b204be00a7162a7ea318b0a889f127e3a894e95ad3c",
        "retrieved_at": "2026-07-23T15:00:00Z",
        "url": "https://emanual.robotis.com/docs/en/platform/turtlebot3/features/"
      },
      {
        "evidence_class": "manufacturer_primary",
        "evidence_id": "RBTX:EV:019f8f7d-9595-7cec-b493-54210abe02a5",
        "locator": "Release 2.3.6",
        "publisher": "ROBOTIS-GIT",
        "response_sha256": "b3b09a7080c4c60f07831a484124020a684e6a8fe13d97001470efba4510b13a",
        "retrieved_at": "2026-07-23T15:00:00Z",
        "url": "https://github.com/ROBOTIS-GIT/turtlebot3/releases/tag/2.3.6"
      },
      {
        "evidence_class": "manufacturer_primary",
        "evidence_id": "RBTX:EV:019f8f7d-9596-7554-8882-fbaa2a9beb2a",
        "locator": "Release 4.1.4",
        "publisher": "ROBOTIS-GIT",
        "response_sha256": "25af19dadd4b57d1a3f90c0e98fbbd2d74ea4494f7f95c5b389a13284b1a2c21",
        "retrieved_at": "2026-07-23T15:00:00Z",
        "url": "https://github.com/ROBOTIS-GIT/open_manipulator/releases/tag/4.1.4"
      }
    ],
    "specifications": [
      {
        "assertion_id": "RBTX:A:019f8f7d-9598-78b3-831a-37d111db3b16",
        "claim_class": "manufacturer_claim",
        "conditions": "Manufacturer-published hardware specification. Verify the value against the exact product revision.",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e"
        ],
        "label": "Arm input voltage",
        "predicate": "electrical.input_voltage",
        "value": "12 V"
      },
      {
        "assertion_id": "RBTX:A:019f8f7d-9599-70f9-b750-ab14306459bb",
        "claim_class": "manufacturer_claim",
        "conditions": "The manufacturer count includes one gripper degree of freedom.",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e"
        ],
        "label": "Arm degrees of freedom",
        "predicate": "kinematics.degrees_of_freedom",
        "value": "5"
      },
      {
        "assertion_id": "RBTX:A:019f8f7d-959a-773c-8f5e-6b639041f2a9",
        "claim_class": "manufacturer_claim",
        "conditions": "Manufacturer-published value. The cited table does not state orientation, reach, acceleration, duty cycle, or safety factor.",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e"
        ],
        "label": "Arm payload (manufacturer claim)",
        "predicate": "performance.payload",
        "value": "0.5 kg"
      },
      {
        "assertion_id": "RBTX:A:019f8f7d-959b-7d55-825b-f96d8b8bc3a3",
        "claim_class": "manufacturer_claim",
        "conditions": "Manufacturer-published value. The cited table does not state the test method or operating conditions.",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e"
        ],
        "label": "Arm repeatability (manufacturer claim)",
        "predicate": "performance.repeatability",
        "value": "< 0.2 mm"
      },
      {
        "assertion_id": "RBTX:A:019f8f7d-959c-71c1-8d41-47482970f1ec",
        "claim_class": "manufacturer_claim",
        "conditions": "The manufacturer summary lists 700 g. A separate inertia section lists 711.37 g.",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e"
        ],
        "label": "Arm summary mass",
        "predicate": "physical.mass",
        "value": "0.7 kg"
      },
      {
        "assertion_id": "RBTX:A:019f8f7d-959d-71da-8aaa-942d46ad8a45",
        "claim_class": "manufacturer_claim",
        "conditions": "Manufacturer-published value. The cited table does not state the reference frame.",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e"
        ],
        "label": "Arm reach",
        "predicate": "geometry.reach",
        "value": "380 mm"
      },
      {
        "assertion_id": "RBTX:A:019f8f7d-959e-7a8b-9a2f-7ddb960da015",
        "claim_class": "manufacturer_claim",
        "conditions": "Manufacturer-published summary specification.",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9593-78dc-99d4-1e268039db1e"
        ],
        "label": "Gripper stroke",
        "predicate": "geometry.gripper_stroke",
        "value": "20-75 mm"
      },
      {
        "assertion_id": "RBTX:A:019f8f7d-95a0-7f27-9128-82fa92e441c5",
        "claim_class": "manufacturer_claim",
        "conditions": "Manufacturer-published dimensions for the Waffle Pi variant.",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9594-7e39-8a42-80cccc977f82"
        ],
        "label": "Base envelope",
        "predicate": "geometry.envelope",
        "value": "281x306x141 mm"
      },
      {
        "assertion_id": "RBTX:A:019f8f7d-95a1-708d-8c51-8ab968d7354f",
        "claim_class": "manufacturer_claim",
        "conditions": "The manufacturer states that the instructions were tested on this operating-system and ROS combination. Confirm package, firmware, and patch versions.",
        "evidence_ids": [
          "RBTX:EV:019f8f7d-9592-701a-8bcc-b11e42d541ae"
        ],
        "label": "Documented test baseline",
        "predicate": "software.tested_baseline",
        "value": "Ubuntu 22.04 and ROS 2 Humble Hawksbill"
      }
    ],
    "status": {
      "label": "Documentation reviewed",
      "verified_on": "2026-07-23"
    },
    "summary": "A documented TurtleBot3 configuration pairing the Waffle Pi mobile base with OpenMANIPULATOR-X. Manufacturer sources describe the relationship. Review the compatibility section for exact revision, power, software, safety, and integration conditions."
  },
  "payload_sha256": "8e859aaedfac1e7204399d050ec0da19f71f00113842edd9622c969dad4deb52",
  "projection_state": "candidate",
  "snapshot_id": "RBTX:S:019f8ff9-bcc4-7872-ab79-4a4d594d0aa3",
  "source_dataset_id": "RBTX:S:019f8f7d-996c-7c8f-9035-1e398f9aa36f",
  "source_dataset_sha256": "6bcf98e577786db49a2fd11dfbea20daf240e2dec34dfa27713c419ea5e09707"
}
ROBBOTTX_RECORD,
    true,
    512,
    JSON_THROW_ON_ERROR
);
