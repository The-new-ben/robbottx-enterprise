<?php

declare(strict_types=1);

namespace RobbottX\Core\Publication;

final class SnapshotRepository
{
    /**
     * @return array<string, mixed>
     */
    public function loadGoldenSlice(): array
    {
        $filePath = ROBBOTTX_CORE_DIR
            . 'resources'
            . DIRECTORY_SEPARATOR
            . 'publication'
            . DIRECTORY_SEPARATOR
            . 'golden-slice.v0.json';

        if (! is_readable($filePath)) {
            throw new \RuntimeException('Publication snapshot is missing.');
        }

        $raw = file_get_contents($filePath);
        if ($raw === false) {
            throw new \RuntimeException('Publication snapshot cannot be read.');
        }

        $snapshot = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        if (! is_array($snapshot) || ! isset($snapshot['payload'])) {
            throw new \UnexpectedValueException('Publication snapshot is malformed.');
        }

        $expectedHash = (string) ($snapshot['payload_sha256'] ?? '');
        $actualHash   = hash(
            'sha256',
            (string) wp_json_encode(
                $this->sortRecursively($snapshot['payload']),
                JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
            )
        );

        if (
            preg_match('/^[0-9a-f]{64}$/', $expectedHash) !== 1
            || ! hash_equals($expectedHash, $actualHash)
        ) {
            throw new \UnexpectedValueException(
                'Publication snapshot hash mismatch.'
            );
        }

        return $snapshot;
    }

    private function sortRecursively(mixed $value): mixed
    {
        if (! is_array($value)) {
            return $value;
        }

        if (array_is_list($value)) {
            return array_map(array($this, 'sortRecursively'), $value);
        }

        ksort($value, SORT_STRING);
        foreach ($value as $key => $child) {
            $value[$key] = $this->sortRecursively($child);
        }

        return $value;
    }
}
