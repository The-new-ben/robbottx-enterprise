<?php

declare(strict_types=1);

use RobbottX\Core\Presentation\FlagshipSystemRenderer;

if (! defined('ABSPATH')) {
    exit;
}

try {
    echo FlagshipSystemRenderer::render(); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
} catch (Throwable $exception) {
    if (current_user_can('manage_options')) {
        echo '<p class="rbtx-record-error">';
        echo esc_html__(
            'The flagship system experience could not be rendered.',
            'robbottx-core'
        );
        echo '</p>';
    }
}
