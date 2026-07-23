<?php

declare(strict_types=1);

$scenario = $argv[1] ?? 'front';
$conditionNames = array(
    'is_woocommerce',
    'is_shop',
    'is_product',
    'is_product_taxonomy',
    'is_cart',
    'is_checkout',
    'is_account_page',
    'is_wc_endpoint_url',
);

$GLOBALS['rbtx_conditions'] = array_fill_keys($conditionNames, false);
$GLOBALS['rbtx_is_admin'] = $scenario === 'admin';
$GLOBALS['rbtx_is_front_page'] = ! in_array(
    $scenario,
    array('admin', 'normal'),
    true
);
$GLOBALS['rbtx_styles'] = array();
$GLOBALS['rbtx_scripts'] = array();

if (array_key_exists($scenario, $GLOBALS['rbtx_conditions'])) {
    $GLOBALS['rbtx_conditions'][$scenario] = true;
}

function is_admin(): bool
{
    return $GLOBALS['rbtx_is_admin'];
}

function is_front_page(): bool
{
    return $GLOBALS['rbtx_is_front_page'];
}

function is_woocommerce(): bool
{
    return $GLOBALS['rbtx_conditions']['is_woocommerce'];
}

function is_shop(): bool
{
    return $GLOBALS['rbtx_conditions']['is_shop'];
}

function is_product(): bool
{
    return $GLOBALS['rbtx_conditions']['is_product'];
}

function is_product_taxonomy(): bool
{
    return $GLOBALS['rbtx_conditions']['is_product_taxonomy'];
}

function is_cart(): bool
{
    return $GLOBALS['rbtx_conditions']['is_cart'];
}

function is_checkout(): bool
{
    return $GLOBALS['rbtx_conditions']['is_checkout'];
}

function is_account_page(): bool
{
    return $GLOBALS['rbtx_conditions']['is_account_page'];
}

function is_wc_endpoint_url(): bool
{
    return $GLOBALS['rbtx_conditions']['is_wc_endpoint_url'];
}

function wp_dequeue_style(string $handle): void
{
    $GLOBALS['rbtx_styles'][] = $handle;
}

function wp_dequeue_script(string $handle): void
{
    $GLOBALS['rbtx_scripts'][] = $handle;
}

require dirname(__DIR__, 2)
    . '/wp-content/plugins/robbottx-core/src/Presentation/Assets.php';

\RobbottX\Core\Presentation\Assets::dequeueUnusedFrontPageAssets();

echo json_encode(
    array(
        'styles' => $GLOBALS['rbtx_styles'],
        'scripts' => $GLOBALS['rbtx_scripts'],
    ),
    JSON_THROW_ON_ERROR
);
