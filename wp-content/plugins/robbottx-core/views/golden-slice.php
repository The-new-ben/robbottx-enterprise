<?php
/**
 * Golden-slice projection view.
 *
 * @var array<string, mixed> $payload
 * @var array<string, mixed> $snapshot
 */

declare(strict_types=1);

if (! defined('ABSPATH')) {
    exit;
}

$identity      = is_array($payload['identity'] ?? null) ? $payload['identity'] : array();
$status        = is_array($payload['status'] ?? null) ? $payload['status'] : array();
$evidence      = is_array($payload['evidence_summary'] ?? null) ? $payload['evidence_summary'] : array();
$specifications = is_array($payload['specifications'] ?? null) ? $payload['specifications'] : array();
$compatibility = is_array($payload['compatibility'] ?? null) ? $payload['compatibility'] : array();
$sources       = is_array($payload['sources'] ?? null) ? $payload['sources'] : array();
$disclosures   = is_array($payload['disclosures'] ?? null) ? $payload['disclosures'] : array();
?>
<section class="rbtx-featured-configuration" id="featured-configuration" aria-labelledby="rbtx-featured-configuration-title">
    <div class="rbtx-section-heading">
        <div>
            <p class="rbtx-eyebrow"><?php esc_html_e('Featured system configuration', 'robbottx-core'); ?></p>
            <h2 id="rbtx-featured-configuration-title"><?php echo esc_html((string) ($identity['name'] ?? '')); ?></h2>
        </div>
        <span class="rbtx-status rbtx-status--documented">
            <span aria-hidden="true"></span>
            <?php echo esc_html((string) ($status['label'] ?? '')); ?>
        </span>
    </div>

    <p class="rbtx-lede"><?php echo esc_html((string) ($payload['summary'] ?? '')); ?></p>

    <dl class="rbtx-evidence-ribbon" aria-label="<?php esc_attr_e('Evidence summary', 'robbottx-core'); ?>">
        <div>
            <dt><?php esc_html_e('RobbottX record ID', 'robbottx-core'); ?></dt>
            <dd><code><?php echo esc_html((string) ($identity['canonical_id'] ?? '')); ?></code></dd>
        </div>
        <div>
            <dt><?php esc_html_e('Source documents', 'robbottx-core'); ?></dt>
            <dd><?php echo esc_html((string) ($evidence['primary_sources'] ?? '0')); ?></dd>
        </div>
        <div>
            <dt><?php esc_html_e('Sourced technical claims', 'robbottx-core'); ?></dt>
            <dd><?php echo esc_html((string) ($evidence['assertion_count'] ?? '0')); ?></dd>
        </div>
        <div>
            <dt><?php esc_html_e('System relationships', 'robbottx-core'); ?></dt>
            <dd><?php echo esc_html((string) ($evidence['relationship_count'] ?? '0')); ?></dd>
        </div>
        <div>
            <dt><?php esc_html_e('Last reviewed', 'robbottx-core'); ?></dt>
            <dd><time datetime="<?php echo esc_attr((string) ($status['verified_on'] ?? '')); ?>"><?php echo esc_html((string) ($status['verified_on'] ?? '')); ?></time></dd>
        </div>
    </dl>

    <div class="rbtx-slice-grid">
        <div class="rbtx-panel">
            <p class="rbtx-panel-kicker"><?php esc_html_e('Manufacturer-published specifications', 'robbottx-core'); ?></p>
            <dl class="rbtx-spec-list">
                <?php foreach ($specifications as $specification) : ?>
                    <div>
                        <dt><?php echo esc_html((string) ($specification['label'] ?? '')); ?></dt>
                        <dd><?php echo esc_html((string) ($specification['value'] ?? '')); ?></dd>
                    </div>
                <?php endforeach; ?>
            </dl>
            <p class="rbtx-caption">
                <?php esc_html_e('Values are normalized for comparison. Review the source documents and compatibility conditions below.', 'robbottx-core'); ?>
            </p>
        </div>

        <div class="rbtx-panel rbtx-panel--dark">
            <p class="rbtx-panel-kicker"><?php esc_html_e('Compatibility notes', 'robbottx-core'); ?></p>
            <h3><?php esc_html_e('Confirm the exact Waffle variant before integration.', 'robbottx-core'); ?></h3>
            <p><?php esc_html_e('Manufacturer compatibility text names Waffle, while its assembly documentation names Waffle Pi. Check exact revisions, mounting hardware, power, pinout, stability, and safety for the intended application.', 'robbottx-core'); ?></p>
            <div class="rbtx-verdict">
                <span><?php esc_html_e('Configuration status', 'robbottx-core'); ?></span>
                <strong><?php esc_html_e('Requires application validation', 'robbottx-core'); ?></strong>
            </div>
        </div>
    </div>

    <div class="rbtx-compatibility" id="verify">
        <div class="rbtx-subheading">
            <p class="rbtx-eyebrow"><?php esc_html_e('Compatibility', 'robbottx-core'); ?></p>
            <h3><?php esc_html_e('Compatibility across 10 technical areas.', 'robbottx-core'); ?></h3>
        </div>
        <div class="rbtx-compatibility-grid">
            <?php foreach ($compatibility as $result) : ?>
                <?php $state = sanitize_html_class((string) ($result['state'] ?? 'unverified')); ?>
                <article class="rbtx-compatibility-card rbtx-state--<?php echo esc_attr($state); ?>">
                    <div class="rbtx-card-topline">
                        <h4><?php echo esc_html((string) ($result['label'] ?? '')); ?></h4>
                        <span><?php echo esc_html((string) ($result['state_label'] ?? '')); ?></span>
                    </div>
                    <p><?php echo esc_html((string) ($result['basis'] ?? '')); ?></p>
                    <p class="rbtx-condition"><?php echo esc_html((string) ($result['conditions'] ?? '')); ?></p>
                </article>
            <?php endforeach; ?>
        </div>
    </div>

    <div class="rbtx-sources" id="methodology">
        <div class="rbtx-subheading">
            <p class="rbtx-eyebrow"><?php esc_html_e('Technical documents and sources', 'robbottx-core'); ?></p>
            <h3><?php esc_html_e('Manufacturer sources for this configuration.', 'robbottx-core'); ?></h3>
        </div>
        <ol class="rbtx-source-list">
            <?php foreach ($sources as $source) : ?>
                <li>
                    <a href="<?php echo esc_url((string) ($source['url'] ?? '')); ?>" rel="external noopener">
                        <?php echo esc_html((string) ($source['publisher'] ?? '')); ?>
                        <span aria-hidden="true">↗</span>
                    </a>
                    <span><?php echo esc_html((string) ($source['locator'] ?? '')); ?></span>
                    <code><?php echo esc_html(substr((string) ($source['response_sha256'] ?? ''), 0, 12)); ?>…</code>
                </li>
            <?php endforeach; ?>
        </ol>
    </div>

    <ul class="rbtx-disclosures" aria-label="<?php esc_attr_e('Important disclosures', 'robbottx-core'); ?>">
        <?php foreach ($disclosures as $disclosure) : ?>
            <li><?php echo esc_html((string) $disclosure); ?></li>
        <?php endforeach; ?>
    </ul>
</section>
