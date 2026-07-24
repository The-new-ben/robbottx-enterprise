<?php
/**
 * Flagship system experience.
 *
 * @var list<array<string, mixed>> $systems
 * @var list<string> $materials
 * @var array{systems: int, assemblies: int, components: int, materials: int} $counts
 * @var string $imageUrl
 */

declare(strict_types=1);

if (! defined('ABSPATH')) {
    exit;
}

$firstSystem = $systems[0];
$systemsJson = wp_json_encode(
    $systems,
    JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT
);
?>
<div class="rbtx-flagship-experience rbtx-flagship-stage" data-rbtx-system-view="interactive-bom-pyramid">
    <section class="rbtx-flagship-hero-section rbtx-flagship-shell" id="flagship" aria-labelledby="rbtx-flagship-title">
        <div class="rbtx-flagship-hero">
            <div class="rbtx-flagship-copy">
                <div class="rbtx-flagship-kicker">
                    <span><?php esc_html_e('RobbottX flagship', 'robbottx-core'); ?></span>
                    <span class="rbtx-concept-badge rbtx-concept-label"><?php esc_html_e('Concept system', 'robbottx-core'); ?></span>
                </div>
                <h1 class="rbtx-flagship-title" id="rbtx-flagship-title"><?php esc_html_e('See the robot as a complete system.', 'robbottx-core'); ?></h1>
                <p class="rbtx-flagship-lede">
                    <?php esc_html_e('A dual-arm mobile robotics concept presented from system architecture to component, material, and interface family.', 'robbottx-core'); ?>
                </p>
                <div class="rbtx-flagship-actions">
                    <a class="rbtx-flagship-button rbtx-flagship-button--primary" href="#system-viewer">
                        <?php esc_html_e('Explore the system', 'robbottx-core'); ?>
                    </a>
                    <a class="rbtx-flagship-button rbtx-flagship-button--secondary" href="#mission-profile">
                        <?php esc_html_e('Build a mission profile', 'robbottx-core'); ?>
                    </a>
                </div>
                <dl class="rbtx-flagship-counts" aria-label="<?php esc_attr_e('Flagship architecture counts', 'robbottx-core'); ?>">
                    <div>
                        <dt><?php esc_html_e('System domains', 'robbottx-core'); ?></dt>
                        <dd><?php echo esc_html((string) $counts['systems']); ?></dd>
                    </div>
                    <div>
                        <dt><?php esc_html_e('Assemblies', 'robbottx-core'); ?></dt>
                        <dd><?php echo esc_html((string) $counts['assemblies']); ?></dd>
                    </div>
                    <div>
                        <dt><?php esc_html_e('Component classes', 'robbottx-core'); ?></dt>
                        <dd><?php echo esc_html((string) $counts['components']); ?></dd>
                    </div>
                </dl>
            </div>

            <figure class="rbtx-flagship-art">
                <div class="rbtx-flagship-halo" aria-hidden="true"></div>
                <img
                    src="<?php echo esc_url($imageUrl); ?>"
                    width="864"
                    height="1821"
                    alt="<?php esc_attr_e('Original RobbottX dual-arm mobile robot concept in a dark product studio', 'robbottx-core'); ?>"
                    decoding="async"
                    fetchpriority="high"
                >
                <figcaption class="screen-reader-text">
                    <?php esc_html_e('Original concept artwork for the interactive flagship system.', 'robbottx-core'); ?>
                </figcaption>
                <span class="rbtx-art-callout rbtx-art-callout--one"><?php esc_html_e('Bimanual architecture', 'robbottx-core'); ?></span>
                <span class="rbtx-art-callout rbtx-art-callout--two"><?php esc_html_e('Mobile platform', 'robbottx-core'); ?></span>
                <span class="rbtx-art-callout rbtx-art-callout--three"><?php esc_html_e('Modular tool path', 'robbottx-core'); ?></span>
            </figure>
        </div>
        <a class="rbtx-scroll-cue" href="#system-viewer">
            <span><?php esc_html_e('Enter system view', 'robbottx-core'); ?></span>
            <span aria-hidden="true">&darr;</span>
        </a>
    </section>

    <section class="rbtx-system-viewer rbtx-system-map rbtx-flagship-shell" id="system-viewer" aria-labelledby="rbtx-system-viewer-title">
        <div class="rbtx-flagship-section-heading rbtx-section-heading">
            <div>
                <p class="rbtx-flagship-eyebrow"><?php esc_html_e('Interactive architecture', 'robbottx-core'); ?></p>
                <h2 id="rbtx-system-viewer-title"><?php esc_html_e('Rotate the robot. Select a system.', 'robbottx-core'); ?></h2>
            </div>
            <p><?php esc_html_e('Drag, swipe, use the arrow keys, or choose a system domain to trace its place in the architecture.', 'robbottx-core'); ?></p>
        </div>

        <div class="rbtx-viewer-shell">
                <div class="rbtx-canvas-frame rbtx-canvas-wrap">
                    <canvas
                        width="960"
                        height="760"
                        tabindex="0"
                        role="img"
                        aria-label="<?php esc_attr_e('Rotatable three-dimensional concept diagram of the RobbottX flagship system', 'robbottx-core'); ?>"
                        data-rbtx-canvas
                    ></canvas>
                    <img
                        class="rbtx-canvas-fallback"
                        src="<?php echo esc_url($imageUrl); ?>"
                        width="864"
                        height="1821"
                        alt="<?php esc_attr_e('Static view of the RobbottX flagship concept', 'robbottx-core'); ?>"
                        loading="lazy"
                        decoding="async"
                        data-rbtx-canvas-fallback
                    >
                    <div class="rbtx-viewer-hotspots" aria-label="<?php esc_attr_e('Interactive robot system hotspots', 'robbottx-core'); ?>">
                        <?php foreach ($systems as $index => $system) : ?>
                            <button
                                type="button"
                                data-rbtx-system="<?php echo esc_attr((string) $system['id']); ?>"
                                aria-pressed="<?php echo $index === 0 ? 'true' : 'false'; ?>"
                            >
                                <?php echo esc_html((string) $system['label']); ?>
                            </button>
                        <?php endforeach; ?>
                    </div>
                    <div class="rbtx-viewer-label" aria-hidden="true">
                        <span></span>
                        <?php esc_html_e('System concept view', 'robbottx-core'); ?>
                    </div>
                    <div class="rbtx-viewer-controls" aria-label="<?php esc_attr_e('Viewer controls', 'robbottx-core'); ?>">
                        <button type="button" data-rbtx-view-action="explode" aria-pressed="false">
                            <?php esc_html_e('Exploded view', 'robbottx-core'); ?>
                        </button>
                        <button type="button" data-rbtx-view-action="reset">
                            <?php esc_html_e('Reset view', 'robbottx-core'); ?>
                        </button>
                    </div>
                <p class="rbtx-viewer-help rbtx-viewer-note">
                    <?php esc_html_e('Pointer drag rotates. Mouse wheel zooms. Arrow keys rotate from the keyboard.', 'robbottx-core'); ?>
                </p>
            </div>
        </div>

            <div class="rbtx-system-explorer rbtx-system-layout">
                <div class="rbtx-system-selector" aria-label="<?php esc_attr_e('Robot system domains', 'robbottx-core'); ?>">
                    <?php foreach ($systems as $index => $system) : ?>
                        <button
                            type="button"
                            data-rbtx-system="<?php echo esc_attr((string) $system['id']); ?>"
                            aria-pressed="<?php echo $index === 0 ? 'true' : 'false'; ?>"
                        >
                            <span class="rbtx-system-number"><?php echo esc_html((string) $system['number']); ?></span>
                            <strong><?php echo esc_html((string) $system['label']); ?></strong>
                        </button>
                    <?php endforeach; ?>
                </div>

                <article class="rbtx-system-detail" aria-live="polite">
                    <p class="rbtx-system-detail-label"><?php esc_html_e('Selected system', 'robbottx-core'); ?></p>
                    <h3 data-rbtx-detail-title><?php echo esc_html((string) $firstSystem['label']); ?></h3>
                    <p data-rbtx-detail-summary><?php echo esc_html((string) $firstSystem['summary']); ?></p>
                    <div class="rbtx-system-detail-grid rbtx-detail-columns">
                        <div>
                            <h4><?php esc_html_e('Assemblies', 'robbottx-core'); ?></h4>
                            <ul data-rbtx-detail-assemblies>
                                <?php foreach ($firstSystem['assemblies'] as $assembly) : ?>
                                    <li><?php echo esc_html((string) $assembly); ?></li>
                                <?php endforeach; ?>
                            </ul>
                        </div>
                        <div>
                            <h4><?php esc_html_e('Component classes', 'robbottx-core'); ?></h4>
                            <ul data-rbtx-detail-components>
                                <?php foreach ($firstSystem['components'] as $component) : ?>
                                    <li><?php echo esc_html((string) $component); ?></li>
                                <?php endforeach; ?>
                            </ul>
                        </div>
                    </div>
                </article>
            </div>
        <?php if (is_string($systemsJson)) : ?>
            <script type="application/json" data-rbtx-system-data><?php echo $systemsJson; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?></script>
        <?php endif; ?>
    </section>

    <section class="rbtx-bom-section rbtx-flagship-shell" id="bom-pyramid" aria-labelledby="rbtx-bom-title">
        <div class="rbtx-flagship-section-heading rbtx-section-heading">
            <div>
                <p class="rbtx-flagship-eyebrow rbtx-eyebrow"><?php esc_html_e('Bill of materials pyramid', 'robbottx-core'); ?></p>
                <h2 id="rbtx-bom-title"><?php esc_html_e('Five levels. One connected architecture.', 'robbottx-core'); ?></h2>
            </div>
            <p><?php esc_html_e('The pyramid links the complete system to domains, assemblies, component classes, and public material and interface families.', 'robbottx-core'); ?></p>
        </div>

        <ol class="rbtx-bom-pyramid rbtx-bom-levels" aria-label="<?php esc_attr_e('Five-level bill of materials hierarchy', 'robbottx-core'); ?>">
            <li>
                <span><?php esc_html_e('Level 0', 'robbottx-core'); ?></span>
                <strong><?php esc_html_e('Complete system', 'robbottx-core'); ?></strong>
                <b>1</b>
            </li>
            <li>
                <span><?php esc_html_e('Level 1', 'robbottx-core'); ?></span>
                <strong><?php esc_html_e('System domains', 'robbottx-core'); ?></strong>
                <b><?php echo esc_html((string) $counts['systems']); ?></b>
            </li>
            <li>
                <span><?php esc_html_e('Level 2', 'robbottx-core'); ?></span>
                <strong><?php esc_html_e('Assemblies', 'robbottx-core'); ?></strong>
                <b><?php echo esc_html((string) $counts['assemblies']); ?></b>
            </li>
            <li>
                <span><?php esc_html_e('Level 3', 'robbottx-core'); ?></span>
                <strong><?php esc_html_e('Component classes', 'robbottx-core'); ?></strong>
                <b><?php echo esc_html((string) $counts['components']); ?></b>
            </li>
            <li>
                <span><?php esc_html_e('Level 4', 'robbottx-core'); ?></span>
                <strong><?php esc_html_e('Material and interface families', 'robbottx-core'); ?></strong>
                <b><?php echo esc_html((string) $counts['materials']); ?></b>
            </li>
        </ol>

        <div class="rbtx-domain-worlds">
            <?php foreach ($systems as $index => $system) : ?>
                <details <?php echo $index === 0 ? 'open' : ''; ?>>
                    <summary>
                        <span><?php echo esc_html((string) $system['number']); ?></span>
                        <strong><?php echo esc_html((string) $system['label']); ?></strong>
                        <small>
                            <?php
                            printf(
                                esc_html__('%1$d assemblies, %2$d component classes', 'robbottx-core'),
                                count($system['assemblies']),
                                count($system['components'])
                            );
                            ?>
                        </small>
                    </summary>
                    <div class="rbtx-world-content">
                        <div>
                            <h3><?php esc_html_e('Assemblies', 'robbottx-core'); ?></h3>
                            <ul>
                                <?php foreach ($system['assemblies'] as $assembly) : ?>
                                    <li><?php echo esc_html((string) $assembly); ?></li>
                                <?php endforeach; ?>
                            </ul>
                        </div>
                        <div>
                            <h3><?php esc_html_e('Component classes', 'robbottx-core'); ?></h3>
                            <ul>
                                <?php foreach ($system['components'] as $component) : ?>
                                    <li><?php echo esc_html((string) $component); ?></li>
                                <?php endforeach; ?>
                            </ul>
                        </div>
                    </div>
                </details>
            <?php endforeach; ?>
        </div>

        <div class="rbtx-material-families">
            <div>
                <p class="rbtx-flagship-eyebrow"><?php esc_html_e('Level 4', 'robbottx-core'); ?></p>
                <h3><?php esc_html_e('Material and interface families', 'robbottx-core'); ?></h3>
            </div>
            <ul>
                <?php foreach ($materials as $material) : ?>
                    <li><?php echo esc_html($material); ?></li>
                <?php endforeach; ?>
            </ul>
        </div>
    </section>

    <section class="rbtx-mission-profile rbtx-mission-section rbtx-flagship-shell" aria-labelledby="rbtx-mission-title">
        <div class="rbtx-mission-panel">
        <div class="rbtx-profile-intro">
            <p class="rbtx-flagship-eyebrow rbtx-eyebrow"><?php esc_html_e('Mission configuration', 'robbottx-core'); ?></p>
            <h2 id="rbtx-mission-title"><?php esc_html_e('Turn the task into a system brief.', 'robbottx-core'); ?></h2>
            <p><?php esc_html_e('Choose the mission, work envelope, interaction model, and operating setting. RobbottX will assemble the choices into a concise application brief.', 'robbottx-core'); ?></p>
        </div>

        <div class="rbtx-mission-workspace">
        <form class="rbtx-profile-form" id="mission-profile" action="#mission-profile" method="get" data-rbtx-profile-form>
            <label>
                <span><?php esc_html_e('Mission', 'robbottx-core'); ?></span>
                <select name="mission">
                    <option><?php esc_html_e('Intralogistics', 'robbottx-core'); ?></option>
                    <option><?php esc_html_e('Machine tending', 'robbottx-core'); ?></option>
                    <option><?php esc_html_e('Kitting and assembly support', 'robbottx-core'); ?></option>
                    <option><?php esc_html_e('Inspection rounds', 'robbottx-core'); ?></option>
                </select>
            </label>
            <label>
                <span><?php esc_html_e('Work envelope', 'robbottx-core'); ?></span>
                <select name="envelope">
                    <option><?php esc_html_e('Compact cell', 'robbottx-core'); ?></option>
                    <option><?php esc_html_e('Standard work area', 'robbottx-core'); ?></option>
                    <option><?php esc_html_e('Extended line coverage', 'robbottx-core'); ?></option>
                </select>
            </label>
            <label>
                <span><?php esc_html_e('Interaction model', 'robbottx-core'); ?></span>
                <select name="interaction">
                    <option><?php esc_html_e('Guarded automation', 'robbottx-core'); ?></option>
                    <option><?php esc_html_e('Supervised collaboration', 'robbottx-core'); ?></option>
                    <option><?php esc_html_e('Remote operation', 'robbottx-core'); ?></option>
                </select>
            </label>
            <label>
                <span><?php esc_html_e('Operating setting', 'robbottx-core'); ?></span>
                <select name="setting">
                    <option><?php esc_html_e('Controlled indoor', 'robbottx-core'); ?></option>
                    <option><?php esc_html_e('Logistics floor', 'robbottx-core'); ?></option>
                    <option><?php esc_html_e('Industrial production', 'robbottx-core'); ?></option>
                </select>
            </label>
            <button type="submit" data-rbtx-build-brief>
                <?php esc_html_e('Create application brief', 'robbottx-core'); ?>
            </button>
        </form>

        <div class="rbtx-profile-output" hidden data-rbtx-brief-output aria-live="polite">
            <div>
                <p class="rbtx-flagship-eyebrow"><?php esc_html_e('Application brief', 'robbottx-core'); ?></p>
                <p data-rbtx-brief-text></p>
            </div>
            <button type="button" data-rbtx-copy-brief>
                <?php esc_html_e('Copy brief', 'robbottx-core'); ?>
            </button>
        </div>
        </div>
        </div>
    </section>
</div>
