<?php

declare(strict_types=1);

namespace RobbottX\Core\Projection;

final class PostTypes
{
    /**
     * @return list<string>
     */
    public static function supported(): array
    {
        return array('rbtx_entity', 'rbtx_config');
    }

    public static function register(): void
    {
        register_post_type(
            'rbtx_entity',
            self::arguments(
                __('Atlas entities', 'robbottx-core'),
                __('Atlas entity', 'robbottx-core'),
                'atlas/entity',
                'dashicons-networking'
            )
        );

        register_post_type(
            'rbtx_config',
            self::arguments(
                __('Configurations', 'robbottx-core'),
                __('Configuration', 'robbottx-core'),
                'atlas/configuration',
                'dashicons-screenoptions'
            )
        );
    }

    /**
     * @return array<string, mixed>
     */
    private static function arguments(
        string $plural,
        string $singular,
        string $slug,
        string $icon
    ): array {
        return array(
            'labels' => array(
                'name'          => $plural,
                'singular_name' => $singular,
                'add_new_item'  => sprintf(
                    /* translators: %s: projection type. */
                    __('Add %s projection', 'robbottx-core'),
                    $singular
                ),
                'edit_item'     => sprintf(
                    /* translators: %s: projection type. */
                    __('Edit %s projection', 'robbottx-core'),
                    $singular
                ),
            ),
            'public'              => true,
            'publicly_queryable'  => true,
            'show_ui'             => true,
            'show_in_rest'        => true,
            'has_archive'         => false,
            'rewrite'             => array(
                'slug'       => $slug,
                'with_front' => false,
            ),
            'supports'            => array(
                'title',
                'editor',
                'excerpt',
                'revisions',
                'custom-fields',
            ),
            'menu_icon'           => $icon,
            'map_meta_cap'        => true,
            'delete_with_user'    => false,
            'exclude_from_search' => false,
        );
    }
}
