<?php

declare(strict_types=1);

namespace RobbottX\Core\Presentation;

final class Seo
{
    private const HOME_DESCRIPTION = 'Explore robotics systems, components, software, compatibility records, and technical documents with RobbottX.';

    private static bool $rankMathDescriptionHandled = false;
    private static bool $rankMathJsonLdHandled = false;

    public static function boot(): void
    {
        add_filter(
            'rank_math/frontend/description',
            array(self::class, 'filterRankMathDescription'),
            99
        );
        add_filter(
            'rank_math/json_ld',
            array(self::class, 'filterRankMathJsonLd'),
            99,
            2
        );
        add_action(
            'wp_head',
            array(self::class, 'renderFallbackHead'),
            PHP_INT_MAX
        );
    }

    public static function filterRankMathDescription(mixed $description): mixed
    {
        if (! is_front_page()) {
            return $description;
        }

        self::$rankMathDescriptionHandled = true;

        return self::HOME_DESCRIPTION;
    }

    /**
     * @param array<string, mixed> $data
     * @return array<string, mixed>
     */
    public static function filterRankMathJsonLd(
        array $data,
        mixed $jsonLd
    ): array {
        if (! is_front_page()) {
            return $data;
        }

        self::$rankMathJsonLdHandled = true;

        foreach (self::entities() as $key => $entity) {
            $data[$key] = $entity;
        }

        return $data;
    }

    public static function renderFallbackHead(): void
    {
        if (! is_front_page()) {
            return;
        }

        if (! self::$rankMathDescriptionHandled) {
            echo '<meta name="description" content="';
            echo esc_attr(self::HOME_DESCRIPTION);
            echo '">' . "\n";
        }

        if (! self::$rankMathJsonLdHandled) {
            $schema = array(
                '@context' => 'https://schema.org',
                '@graph'   => array_values(self::entities()),
            );
            $encoded = wp_json_encode($schema, JSON_UNESCAPED_UNICODE);

            if (is_string($encoded)) {
                echo '<script type="application/ld+json">';
                echo $encoded;
                echo '</script>' . "\n";
            }
        }
    }

    /**
     * @return array<string, array<string, mixed>>
     */
    private static function entities(): array
    {
        $homeUrl = home_url('/');
        $name    = (string) get_bloginfo('name');
        $tagline = (string) get_bloginfo('description');
        $language = (string) get_bloginfo('language');
        $pageName = trim($name . ($tagline !== '' ? ': ' . $tagline : ''));

        return array(
            'WebSite' => array(
                '@type'       => 'WebSite',
                '@id'         => $homeUrl . '#website',
                'url'         => $homeUrl,
                'name'        => $name,
                'description' => self::HOME_DESCRIPTION,
                'inLanguage'  => $language,
            ),
            'WebPage' => array(
                '@type'       => 'WebPage',
                '@id'         => $homeUrl . '#webpage',
                'url'         => $homeUrl,
                'name'        => $pageName,
                'description' => self::HOME_DESCRIPTION,
                'inLanguage'  => $language,
                'isPartOf'    => array(
                    '@id' => $homeUrl . '#website',
                ),
            ),
        );
    }
}
