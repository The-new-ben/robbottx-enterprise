<?php

declare(strict_types=1);

namespace RobbottX\Core\Presentation;

final class Assets
{
    /**
     * Third-party styles loaded globally despite not being used by the catalog
     * homepage. Commerce views are explicitly excluded before these are removed.
     *
     * @var list<string>
     */
    private const FRONT_PAGE_STYLE_HANDLES = array(
        'searchandfilter',
        'woocommerce-layout',
        'woocommerce-smallscreen',
        'woocommerce-general',
        'woocommerce-blocktheme',
        'woocommerce-inline',
        'brands-styles',
        'wc-blocks-style',
        'site-reviews',
    );

    /**
     * Top-level third-party scripts unused by the catalog homepage.
     * Shared dependencies remain registered for any legitimate consumer.
     *
     * @var list<string>
     */
    private const FRONT_PAGE_SCRIPT_HANDLES = array(
        'wc-add-to-cart',
        'woocommerce',
        'sourcebuster-js',
        'wc-order-attribution',
        'site-reviews',
    );

    private const RESPONSIVE_CSS = <<<'CSS'
.rbtx-featured-configuration #rbtx-featured-configuration-title,
.rbtx-featured-configuration code,
.rbtx-featured-configuration dd,
.rbtx-featured-configuration a {
    overflow-wrap: anywhere;
}
CSS;

    public static function enqueue(): void
    {
        wp_register_style(
            'robbottx-core',
            false,
            array(),
            ROBBOTTX_CORE_VERSION
        );
        wp_enqueue_style('robbottx-core');
        wp_add_inline_style('robbottx-core', self::RESPONSIVE_CSS);
    }

    public static function prepareFrontPage(): void
    {
        if (! self::isCatalogFrontPage()) {
            return;
        }

        remove_action('wp_head', 'print_emoji_detection_script', 7);
        remove_action('wp_print_styles', 'print_emoji_styles');
        remove_action('wp_enqueue_scripts', 'wp_enqueue_emoji_styles');
    }

    public static function dequeueUnusedFrontPageAssets(): void
    {
        if (! self::isCatalogFrontPage()) {
            return;
        }

        foreach (self::FRONT_PAGE_STYLE_HANDLES as $handle) {
            wp_dequeue_style($handle);
        }

        foreach (self::FRONT_PAGE_SCRIPT_HANDLES as $handle) {
            wp_dequeue_script($handle);
        }
    }

    private static function isCatalogFrontPage(): bool
    {
        if (is_admin() || ! is_front_page()) {
            return false;
        }

        foreach (
            array(
                'is_woocommerce',
                'is_shop',
                'is_product',
                'is_product_taxonomy',
                'is_cart',
                'is_checkout',
                'is_account_page',
                'is_wc_endpoint_url',
            ) as $conditional
        ) {
            if (function_exists($conditional) && $conditional()) {
                return false;
            }
        }

        return true;
    }
}
