<?php
/**
 * Plugin Name:       RobbottX Core
 * Plugin URI:        https://robbottx.com/
 * Description:       Source-backed robotics records and compatibility views for RobbottX.
 * Version:           0.1.5
 * Requires at least: 6.9
 * Requires PHP:      8.3
 * Author:            RobbottX
 * License:           GPL-2.0-or-later
 * Text Domain:       robbottx-core
 */

declare(strict_types=1);

if (! defined('ABSPATH')) {
    exit;
}

define('ROBBOTTX_CORE_VERSION', '0.1.5');
define('ROBBOTTX_CORE_FILE', __FILE__);
define('ROBBOTTX_CORE_DIR', plugin_dir_path(__FILE__));
define(
    'ROBBOTTX_CORE_MANIFEST_URL',
    'https://raw.githubusercontent.com/The-new-ben/robbottx-enterprise/main/plugin-dist/robbottx-core.json'
);

if (PHP_VERSION_ID < 80300) {
    add_action(
        'admin_notices',
        static function (): void {
            echo '<div class="notice notice-error"><p>';
            echo esc_html__(
                'RobbottX Core requires PHP 8.3 or newer and has not started.',
                'robbottx-core'
            );
            echo '</p></div>';
        }
    );
    return;
}

spl_autoload_register(
    static function (string $className): void {
        $prefix = 'RobbottX\\Core\\';

        if (! str_starts_with($className, $prefix)) {
            return;
        }

        $relativeClass = substr($className, strlen($prefix));
        $relativePath  = str_replace('\\', DIRECTORY_SEPARATOR, $relativeClass);
        $filePath      = ROBBOTTX_CORE_DIR . 'src' . DIRECTORY_SEPARATOR . $relativePath . '.php';

        if (is_readable($filePath)) {
            require_once $filePath;
        }
    }
);

register_activation_hook(
    __FILE__,
    array(\RobbottX\Core\Lifecycle::class, 'activate')
);

register_deactivation_hook(
    __FILE__,
    array(\RobbottX\Core\Lifecycle::class, 'deactivate')
);

add_action(
    'plugins_loaded',
    static function (): void {
        if (version_compare((string) get_bloginfo('version'), '6.9', '<')) {
            add_action(
                'admin_notices',
                static function (): void {
                    echo '<div class="notice notice-error"><p>';
                    echo esc_html__(
                        'RobbottX Core requires WordPress 6.9 or newer and has not started.',
                        'robbottx-core'
                    );
                    echo '</p></div>';
                }
            );
            return;
        }

        (new \RobbottX\Core\Plugin())->boot();
    }
);
