<?php

declare(strict_types=1);

namespace RobbottX\Core;

use RobbottX\Core\Projection\PostTypes;

final class Lifecycle
{
    public static function activate(): void
    {
        PostTypes::register();
        add_option('robbottx_core_version', ROBBOTTX_CORE_VERSION, '', false);
        flush_rewrite_rules(false);
    }

    public static function deactivate(): void
    {
        flush_rewrite_rules(false);
    }
}
