<?php

declare(strict_types=1);

if (! defined('WP_UNINSTALL_PLUGIN')) {
    exit;
}

// Data preservation is mandatory under the owner's no-backup policy.
// Destructive uninstall is intentionally unavailable.
