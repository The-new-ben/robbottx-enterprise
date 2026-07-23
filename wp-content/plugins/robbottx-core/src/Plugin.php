<?php

declare(strict_types=1);

namespace RobbottX\Core;

use RobbottX\Core\Presentation\Blocks;
use RobbottX\Core\Projection\MetaFields;
use RobbottX\Core\Projection\PostTypes;
use RobbottX\Core\Projection\PublicationGate;
use RobbottX\Core\Publication\SnapshotRepository;
use RobbottX\Core\Rest\HealthController;
use RobbottX\Core\Updates\UpdateChecker;

final class Plugin
{
    public function boot(): void
    {
        add_action('init', array(PostTypes::class, 'register'));
        add_action('init', array(MetaFields::class, 'register'));
        add_action('init', array(Blocks::class, 'register'));
        add_action('init', array(UpdateChecker::class, 'boot'), 5);
        add_action(
            'rest_api_init',
            array(HealthController::class, 'registerRoutes')
        );

        add_filter(
            'wp_insert_post_data',
            array(PublicationGate::class, 'enforceBeforeSave'),
            20,
            2
        );
        add_filter('wp_robots', array(PublicationGate::class, 'filterRobots'));
        add_action('admin_notices', array(PublicationGate::class, 'renderNotice'));
        add_action('admin_notices', array($this, 'renderSnapshotHealth'));
    }

    public function renderSnapshotHealth(): void
    {
        if (! current_user_can('manage_options')) {
            return;
        }

        try {
            (new SnapshotRepository())->loadGoldenSlice();
        } catch (\Throwable $exception) {
            echo '<div class="notice notice-error"><p>';
            echo esc_html__(
                'RobbottX Core rejected its publication snapshot because integrity verification failed.',
                'robbottx-core'
            );
            echo '</p></div>';
        }
    }
}
