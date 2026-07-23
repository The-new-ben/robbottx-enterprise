<?php

declare(strict_types=1);

namespace RobbottX\Core\Rest;

use RobbottX\Core\Publication\SnapshotRepository;
use WP_Error;
use WP_REST_Response;
use WP_REST_Server;

final class HealthController
{
    public static function registerRoutes(): void
    {
        register_rest_route(
            'robbottx/v1',
            '/healthcheck',
            array(
                'methods'             => WP_REST_Server::READABLE,
                'callback'            => array(self::class, 'getHealth'),
                'permission_callback' => '__return_true',
                'schema'              => array(self::class, 'getSchema'),
            )
        );
    }

    public static function getHealth(): WP_REST_Response|WP_Error
    {
        try {
            $snapshot = (new SnapshotRepository())->loadGoldenSlice();
        } catch (\Throwable $exception) {
            return new WP_Error(
                'robbottx_snapshot_unhealthy',
                __(
                    'The RobbottX publication snapshot failed integrity verification.',
                    'robbottx-core'
                ),
                array('status' => 503)
            );
        }

        return rest_ensure_response(
            array(
                'status'           => 'ok',
                'version'          => ROBBOTTX_CORE_VERSION,
                'snapshot_id'      => (string) ($snapshot['snapshot_id'] ?? ''),
                'snapshot_hash'    => (string) ($snapshot['payload_sha256'] ?? ''),
                'projection_state' => (string) ($snapshot['projection_state'] ?? ''),
            )
        );
    }

    /**
     * @return array<string, mixed>
     */
    public static function getSchema(): array
    {
        return array(
            '$schema'    => 'http://json-schema.org/draft-04/schema#',
            'title'      => 'robbottx-health',
            'type'       => 'object',
            'properties' => array(
                'status' => array(
                    'type'     => 'string',
                    'readonly' => true,
                ),
                'version' => array(
                    'type'     => 'string',
                    'readonly' => true,
                ),
                'snapshot_id' => array(
                    'type'     => 'string',
                    'readonly' => true,
                ),
                'snapshot_hash' => array(
                    'type'     => 'string',
                    'pattern'  => '^[0-9a-f]{64}$',
                    'readonly' => true,
                ),
                'projection_state' => array(
                    'type'     => 'string',
                    'readonly' => true,
                ),
            ),
        );
    }
}
