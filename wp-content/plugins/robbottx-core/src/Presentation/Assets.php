<?php

declare(strict_types=1);

namespace RobbottX\Core\Presentation;

final class Assets
{
    private const RESPONSIVE_CSS = <<<'CSS'
.rbtx-featured-configuration #rbtx-featured-configuration-title,
.rbtx-featured-configuration code,
.rbtx-featured-configuration dd,
.rbtx-featured-configuration a {
    overflow-wrap: anywhere;
}
CSS;

    public static function enqueue(): void
    {
        wp_register_style(
            'robbottx-core',
            false,
            array(),
            ROBBOTTX_CORE_VERSION
        );
        wp_enqueue_style('robbottx-core');
        wp_add_inline_style('robbottx-core', self::RESPONSIVE_CSS);
    }
}
