<?php

declare(strict_types=1);

namespace RobbottX\Core\Projection;

final class PublicationGate
{
    /**
     * @param array<string, mixed> $data
     * @param array<string, mixed> $postarr
     * @return array<string, mixed>
     */
    public static function enforceBeforeSave(array $data, array $postarr): array
    {
        if (
            ! in_array($data['post_type'] ?? '', PostTypes::supported(), true)
            || ($data['post_status'] ?? '') !== 'publish'
        ) {
            return $data;
        }

        $postId    = isset($postarr['ID']) ? (int) $postarr['ID'] : 0;
        $metaInput = isset($postarr['meta_input']) && is_array($postarr['meta_input'])
            ? $postarr['meta_input']
            : array();

        $eligible = self::metaValue(
            $metaInput,
            $postId,
            'rbtx_publication_eligible'
        );
        $externalId = (string) self::metaValue(
            $metaInput,
            $postId,
            'rbtx_external_id'
        );
        $version = (string) self::metaValue(
            $metaInput,
            $postId,
            'rbtx_snapshot_version'
        );
        $hash = (string) self::metaValue(
            $metaInput,
            $postId,
            'rbtx_snapshot_hash'
        );
        $state = (string) self::metaValue(
            $metaInput,
            $postId,
            'rbtx_projection_state'
        );

        $ready = rest_sanitize_boolean($eligible)
            && preg_match('/^RBTX:(?:E|C):/', $externalId) === 1
            && $version !== ''
            && preg_match('/^[0-9a-f]{64}$/', $hash) === 1
            && $state === 'approved';

        if ($ready) {
            return $data;
        }

        $data['post_status'] = 'draft';
        $userId              = get_current_user_id();

        if ($userId > 0) {
            set_transient(
                'robbottx_publication_gate_' . $userId,
                'blocked',
                MINUTE_IN_SECONDS
            );
        }

        return $data;
    }

    /**
     * @param array<string, bool> $robots
     * @return array<string, bool>
     */
    public static function filterRobots(array $robots): array
    {
        if (! is_singular(PostTypes::supported())) {
            return $robots;
        }

        $postId   = get_queried_object_id();
        $eligible = (bool) get_post_meta(
            $postId,
            'rbtx_publication_eligible',
            true
        );
        $state    = (string) get_post_meta(
            $postId,
            'rbtx_projection_state',
            true
        );

        if (! $eligible || $state !== 'approved') {
            $robots['noindex']  = true;
            $robots['nofollow'] = false;
        }

        return $robots;
    }

    public static function renderNotice(): void
    {
        $userId = get_current_user_id();

        if (
            $userId <= 0
            || get_transient('robbottx_publication_gate_' . $userId) !== 'blocked'
        ) {
            return;
        }

        delete_transient('robbottx_publication_gate_' . $userId);

        echo '<div class="notice notice-error is-dismissible"><p>';
        echo esc_html__(
            'RobbottX kept this projection as a draft: an approved canonical ID, snapshot version, matching SHA-256, approved state, and publication eligibility are required.',
            'robbottx-core'
        );
        echo '</p></div>';
    }

    /**
     * @param array<string, mixed> $metaInput
     */
    private static function metaValue(
        array $metaInput,
        int $postId,
        string $key
    ): mixed {
        if (array_key_exists($key, $metaInput)) {
            return $metaInput[$key];
        }

        return $postId > 0 ? get_post_meta($postId, $key, true) : null;
    }
}
