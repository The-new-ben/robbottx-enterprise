<?php

declare(strict_types=1);

namespace RobbottX\Core\Presentation;

final class GoldenSliceRenderer
{
    /**
     * @param array<string, mixed> $snapshot
     */
    public static function render(array $snapshot): string
    {
        $payload = $snapshot['payload'] ?? null;

        if (! is_array($payload)) {
            return '';
        }

        ob_start();
        require ROBBOTTX_CORE_DIR
            . 'views'
            . DIRECTORY_SEPARATOR
            . 'golden-slice.php';

        return (string) ob_get_clean();
    }
}
