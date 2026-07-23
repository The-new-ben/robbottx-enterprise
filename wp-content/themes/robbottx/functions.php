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
    'init',
    static function (): void {
        register_block_pattern_category(
            'robbottx',
            array('label' => __('RobbottX', 'robbottx'))
        );
    }
);
