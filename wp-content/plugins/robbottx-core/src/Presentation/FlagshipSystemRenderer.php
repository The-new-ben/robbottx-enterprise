<?php

declare(strict_types=1);

namespace RobbottX\Core\Presentation;

final class FlagshipSystemRenderer
{
    public static function render(): string
    {
        $systems = self::systems();
        $materials = self::materials();
        $counts = array(
            'systems'    => count($systems),
            'assemblies' => array_sum(
                array_map(
                    static fn (array $system): int => count($system['assemblies']),
                    $systems
                )
            ),
            'components' => array_sum(
                array_map(
                    static fn (array $system): int => count($system['components']),
                    $systems
                )
            ),
            'materials'  => count($materials),
        );

        if (
            $counts['systems'] !== 8
            || $counts['assemblies'] !== 28
            || $counts['components'] !== 48
            || $counts['materials'] !== 12
        ) {
            throw new \LogicException('Flagship BOM counts are inconsistent.');
        }

        $imageUrl = ROBBOTTX_CORE_URL . 'assets/flagship-concept-v1-648.jpg';

        ob_start();
        require ROBBOTTX_CORE_DIR
            . 'views'
            . DIRECTORY_SEPARATOR
            . 'flagship-system.php';

        return (string) ob_get_clean();
    }

    /**
     * @return list<array{
     *     id: string,
     *     number: string,
     *     label: string,
     *     summary: string,
     *     assemblies: list<string>,
     *     components: list<string>
     * }>
     */
    private static function systems(): array
    {
        return array(
            array(
                'id'         => 'perception',
                'number'     => '01',
                'label'      => 'Perception',
                'summary'    => 'Environmental coverage and robot-state sensing form a shared spatial picture.',
                'assemblies' => array(
                    'Sensor crown',
                    'Near-field coverage',
                    'Robot-state sensing',
                    'Protective field interface',
                ),
                'components' => array(
                    'Panoramic vision',
                    'Depth sensing',
                    'Range sensing',
                    'Tactile inputs',
                    'Inertial reference',
                    'Environmental sensing',
                ),
            ),
            array(
                'id'         => 'compute',
                'number'     => '02',
                'label'      => 'Compute and autonomy',
                'summary'    => 'Real-time motion, task planning, device coordination, and system records stay separated by role.',
                'assemblies' => array(
                    'Real-time control plane',
                    'Task computing',
                    'Device orchestration',
                    'Data and service plane',
                ),
                'components' => array(
                    'Motion controller',
                    'Task computer',
                    'Safety-isolated I/O',
                    'Deterministic network',
                    'System logger',
                    'Service controller',
                ),
            ),
            array(
                'id'         => 'power',
                'number'     => '03',
                'label'      => 'Power and energy',
                'summary'    => 'Stored energy, conversion, distribution, measurement, and charging share one managed power path.',
                'assemblies' => array(
                    'Energy storage',
                    'Power distribution',
                    'Charging and service',
                ),
                'components' => array(
                    'Battery module class',
                    'Contactor and precharge',
                    'DC conversion',
                    'Branch protection',
                    'Energy measurement',
                    'Charge interface',
                ),
            ),
            array(
                'id'         => 'safety',
                'number'     => '04',
                'label'      => 'Safety',
                'summary'    => 'Independent stop, supervision, reset, and status paths define the controlled operating boundary.',
                'assemblies' => array(
                    'Stop and reset chain',
                    'Safe motion supervision',
                    'Human status interface',
                ),
                'components' => array(
                    'Emergency stop loop',
                    'Safety controller',
                    'Protective stop input',
                    'Drive disable path',
                    'Manual reset',
                    'State signalling',
                ),
            ),
            array(
                'id'         => 'mobility',
                'number'     => '05',
                'label'      => 'Mobility',
                'summary'    => 'A low mobile base carries drive, sensing, braking, and load paths as one serviceable platform.',
                'assemblies' => array(
                    'Omnidirectional drive',
                    'Base sensing',
                    'Base structure',
                ),
                'components' => array(
                    'Wheel module class',
                    'Traction drive',
                    'Wheel encoder',
                    'Compliance support',
                    'Braking interface',
                    'Base frame',
                ),
            ),
            array(
                'id'         => 'manipulation',
                'number'     => '06',
                'label'      => 'Manipulation',
                'summary'    => 'Two modular arm chains connect joint motion, load sensing, harness routing, and tool placement.',
                'assemblies' => array(
                    'Left arm chain',
                    'Right arm chain',
                    'Wrist sensing',
                    'Cable management',
                ),
                'components' => array(
                    'Shoulder joint class',
                    'Elbow joint class',
                    'Wrist joint class',
                    'Joint encoder',
                    'Force-torque interface',
                    'Routed harness',
                ),
            ),
            array(
                'id'         => 'tools',
                'number'     => '07',
                'label'      => 'Tools',
                'summary'    => 'A common coupling joins interchangeable end effectors to identity, power, and storage services.',
                'assemblies' => array(
                    'Coupling interface',
                    'End-effector set',
                    'Tool service bay',
                ),
                'components' => array(
                    'Quick-change coupling',
                    'Parallel gripper',
                    'Vacuum option',
                    'Tool identification',
                    'Tool power',
                    'Tool storage',
                ),
            ),
            array(
                'id'         => 'structure',
                'number'     => '08',
                'label'      => 'Structure and thermal',
                'summary'    => 'Frames, shells, heat paths, airflow, and service openings support the rest of the architecture.',
                'assemblies' => array(
                    'Primary load path',
                    'Exterior shell',
                    'Heat transport',
                    'Service access',
                ),
                'components' => array(
                    'Torso frame',
                    'Panel shell',
                    'Joint housing',
                    'Heat spreader',
                    'Forced airflow',
                    'Seal and service door',
                ),
            ),
        );
    }

    /**
     * @return list<string>
     */
    private static function materials(): array
    {
        return array(
            'Load-bearing aluminum family',
            'High-strength steel family',
            'Carbon composite family',
            'Engineering polymer family',
            'Elastomer sealing family',
            'Copper conductor family',
            'Optical glass family',
            'Thermal interface family',
            'Mechanical datum interface',
            'DC power interface',
            'Deterministic fieldbus',
            'Safety I/O interface',
        );
    }
}
