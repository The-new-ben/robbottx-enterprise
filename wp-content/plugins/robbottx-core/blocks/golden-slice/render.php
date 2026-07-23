<?php

declare(strict_types=1);

use RobbottX\Core\Presentation\GoldenSliceRenderer;
use RobbottX\Core\Publication\SnapshotRepository;

if (! defined('ABSPATH')) {
    exit;
}

try {
    $snapshot = (new SnapshotRepository())->loadGoldenSlice();
    echo GoldenSliceRenderer::render($snapshot); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
} catch (Throwable $exception) {
    if (current_user_can('manage_options')) {
        echo '<p class="rbtx-record-error">';
        echo esc_html__(
            'The RobbottX record is unavailable because its integrity check failed.',
            'robbottx-core'
        );
        echo '</p>';
    }
}
