# Golden slice v0

Status: candidate, not publication-eligible  
Date: 2026-07-23

## Purpose

Prove one complete path:

`primary source -> evidence -> assertion -> revision -> BOM -> compatibility
assessment -> publication snapshot -> WordPress rendering`

The candidate is a TurtleBot3 Waffle Pi mobile base with an
OpenMANIPULATOR-X, using Ubuntu 22.04 and ROS 2 Humble as the documented
software baseline.

This is not a mass catalog import. The retired CSV and image collection are
forbidden inputs.

## Why this candidate

ROBOTIS publishes official specifications, assembly instructions, software,
and a documented mobile-manipulator relationship. The system is broad enough
to exercise mechanical, electrical, controller, protocol, software,
performance, safety, 3D, licensing, and supply questions without pretending a
whole-world catalog already exists.

## Current source-backed facts

- ROBOTIS states that OpenMANIPULATOR-X is compatible with TurtleBot3 Waffle
  as a mobile manipulator.
- The hardware-assembly section labels its CAD files for TurtleBot3 Waffle Pi
  plus OpenMANIPULATOR and describes moving an LDS-01 or LDS-02 before mounting
  the arm.
- The instructions state that the current ROS 2 path was tested on Ubuntu
  22.04 and ROS 2 Humble.
- OpenMANIPULATOR-X is specified as 12 V, five degrees of freedom including
  the gripper, 500 g payload, less than 0.2 mm repeatability, 0.70 kg weight,
  380 mm reach, 20-75 mm gripper stroke, and TTL multidrop communication.
- The official TurtleBot3 repository release recorded in the slice is 2.3.6
  dated 2025-12-15.
- The official OpenMANIPULATOR repository release recorded in the slice is
  4.1.4 dated 2026-04-29.

These are manufacturer-published statements. They are not RobbottX physical
test results.

## Deliberately preserved unknowns

1. The textual compatibility claim names Waffle while the assembly section
   names Waffle Pi. Exact applicability requires review.
2. Exact sellable hardware revisions, controller revision, LiDAR choice,
   Raspberry Pi memory variant, firmware, and package versions are not frozen.
3. Mechanical fasteners, mounting stack, center of mass, stability envelope,
   power budget, and emergency-stop strategy are not yet closed.
4. No physical configuration has been inspected or tested by RobbottX.
5. CAD/mesh redistribution rights, revision binding, coordinate frames, scale,
   and checksums are not approved for public 3D delivery.
6. Authorized offers, regions, price, stock, warranty, shipping, taxes, and
   commercial relationships are not frozen.
7. The canonical production service and object-storage hosting path is not yet
   selected.

Unknown never passes as compatible. The overall assessment therefore remains
`engineering_review_required`.

## Release gates

The candidate becomes a canonical indexable configuration only when:

- exact revisions and software baseline are frozen;
- every public numeric assertion has unit, conditions, locator, checksum, and
  evidence class;
- BOM closure and alternates are reviewed;
- all required compatibility dimensions resolve without hidden unknowns;
- approved static and 3D assets have rights and technical metadata;
- offers are region- and time-specific or omitted;
- the publication snapshot is eligible and reproducible;
- WordPress SEO, accessibility, performance, functional, responsive, and
  screenshot gates pass;
- the production change remains additive and code-reversible under the owner's
  no-staging/no-backup constraint.

## Primary source set

- https://emanual.robotis.com/docs/en/platform/turtlebot3/manipulation/
- https://emanual.robotis.com/docs/en/platform/openmanipulator_x/specification/
- https://emanual.robotis.com/docs/en/platform/turtlebot3/features/
- https://github.com/ROBOTIS-GIT/turtlebot3/releases/tag/2.3.6
- https://github.com/ROBOTIS-GIT/open_manipulator/releases/tag/4.1.4
