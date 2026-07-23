<?php
/**
 * RobbottX theme bootstrap.
 *
 * @package RobbottX
 */

declare(strict_types=1);

if (! defined('ABSPATH')) {
    exit;
}

add_action(
    'after_setup_theme',
    static function (): void {
        add_editor_style('style.css');
    }
);

add_action(
    'wp_enqueue_scripts',
    static function (): void {
        $theme = wp_get_theme();
        wp_enqueue_style(
            'robbottx',
            get_stylesheet_uri(),
            array(),
            (string) $theme->get('Version')
        );
    }
);

add_action(
    'wp_head',
    static function (): void {
        if (has_site_icon()) {
            return;
        }

        $theme = wp_get_theme();
        $iconUrl = add_query_arg(
            'ver',
            (string) $theme->get('Version'),
            get_theme_file_uri('assets/favicon.svg')
        );

        printf(
            '<link rel="icon" href="%s" type="image/svg+xml" sizes="any">' . "\n",
            esc_url($iconUrl)
        );
    },
    1
);

add_action(
    'init',
    static function (): void {
        register_block_pattern_category(
            'robbottx',
            array('label' => __('RobbottX', 'robbottx'))
        );
    }
);
