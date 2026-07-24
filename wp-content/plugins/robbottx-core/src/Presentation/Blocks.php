<?php

declare(strict_types=1);

namespace RobbottX\Core\Presentation;

final class Blocks
{
    public static function register(): void
    {
        register_block_type(
            ROBBOTTX_CORE_DIR . 'blocks' . DIRECTORY_SEPARATOR . 'golden-slice'
        );
        register_block_type(
            ROBBOTTX_CORE_DIR . 'blocks' . DIRECTORY_SEPARATOR . 'flagship-system'
        );
    }
}
