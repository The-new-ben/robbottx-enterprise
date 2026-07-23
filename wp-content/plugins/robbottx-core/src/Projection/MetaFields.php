<?php

declare(strict_types=1);

namespace RobbottX\Core\Projection;

final class MetaFields
{
    public static function register(): void
    {
        foreach (PostTypes::supported() as $postType) {
            self::registerField(
                $postType,
                'rbtx_external_id',
                'string',
                array(self::class, 'sanitizeExternalId')
            );
            self::registerField(
                $postType,
                'rbtx_snapshot_version',
                'string',
                'sanitize_text_field'
            );
            self::registerField(
                $postType,
                'rbtx_snapshot_hash',
                'string',
                array(self::class, 'sanitizeHash')
            );
            self::registerField(
                $postType,
                'rbtx_projection_state',
                'string',
                array(self::class, 'sanitizeProjectionState')
            );
            self::registerField(
                $postType,
                'rbtx_publication_eligible',
                'boolean',
                'rest_sanitize_boolean'
            );
        }
    }

    public static function sanitizeExternalId(mixed $value): string
    {
        $candidate = sanitize_text_field((string) $value);

        if (
            preg_match(
                '/^RBTX:(?:E|C):[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/',
                $candidate
            ) !== 1
        ) {
            return '';
        }

        return $candidate;
    }

    public static function sanitizeHash(mixed $value): string
    {
        $candidate = strtolower(sanitize_text_field((string) $value));
        return preg_match('/^[0-9a-f]{64}$/', $candidate) === 1
            ? $candidate
            : '';
    }

    public static function sanitizeProjectionState(mixed $value): string
    {
        $candidate = sanitize_key((string) $value);
        return in_array(
            $candidate,
            array('candidate', 'approved', 'stale', 'withdrawn'),
            true
        ) ? $candidate : 'candidate';
    }

    /**
     * @param callable|string $sanitizeCallback
     */
    private static function registerField(
        string $postType,
        string $key,
        string $type,
        callable|string $sanitizeCallback
    ): void {
        register_post_meta(
            $postType,
            $key,
            array(
                'type'              => $type,
                'single'            => true,
                'show_in_rest'      => true,
                'sanitize_callback' => $sanitizeCallback,
                'auth_callback'     => static function (
                    bool $allowed,
                    string $metaKey,
                    int $postId
                ): bool {
                    unset($allowed, $metaKey);
                    return current_user_can('edit_post', $postId);
                },
            )
        );
    }
}
