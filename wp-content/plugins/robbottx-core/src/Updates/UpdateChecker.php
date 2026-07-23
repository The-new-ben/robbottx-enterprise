<?php

declare(strict_types=1);

namespace RobbottX\Core\Updates;

final class UpdateChecker
{
    public static function boot(): void
    {
        $library = ROBBOTTX_CORE_DIR
            . 'lib'
            . DIRECTORY_SEPARATOR
            . 'plugin-update-checker'
            . DIRECTORY_SEPARATOR
            . 'plugin-update-checker.php';

        if (! is_readable($library)) {
            return;
        }

        require_once $library;

        $factory = '\\YahnisElsts\\PluginUpdateChecker\\v5\\PucFactory';
        if (! class_exists($factory)) {
            return;
        }

        try {
            $factory::buildUpdateChecker(
                ROBBOTTX_CORE_MANIFEST_URL,
                ROBBOTTX_CORE_FILE,
                'robbottx-core'
            );
        } catch (\Throwable $exception) {
            do_action('robbottx_update_checker_error', $exception);
        }
    }
}
