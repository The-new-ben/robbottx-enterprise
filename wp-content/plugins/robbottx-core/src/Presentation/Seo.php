<?php

declare(strict_types=1);

namespace RobbottX\Core\Presentation;

final class Seo
{
    private const HOME_DESCRIPTION = 'Explore the RobbottX flagship robotics concept through an interactive system view, BOM hierarchy, component classes, interfaces, and mission configuration.';

    private static bool $rankMathDescriptionHandled = false;
    private static bool $rankMathJsonLdHandled = false;
    private static bool $rankMathFacebookHandled = false;
    private static bool $rankMathTwitterHandled = false;

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
        add_filter(
            'rank_math/opengraph/facebook/og_title',
            array(self::class, 'filterRankMathFacebookTitle'),
            99
        );
        add_filter(
            'rank_math/opengraph/facebook/og_description',
            array(self::class, 'filterRankMathFacebookDescription'),
            99
        );
        add_filter(
            'rank_math/opengraph/type',
            array(self::class, 'filterRankMathFacebookType'),
            99
        );
        add_filter(
            'rank_math/opengraph/url',
            array(self::class, 'filterRankMathFacebookUrl'),
            99
        );
        add_filter(
            'rank_math/opengraph/facebook/og_site_name',
            array(self::class, 'filterRankMathFacebookSiteName'),
            99
        );
        add_filter(
            'rank_math/opengraph/facebook/og_locale',
            array(self::class, 'filterRankMathFacebookLocale'),
            99
        );
        add_filter(
            'rank_math/opengraph/twitter/twitter_title',
            array(self::class, 'filterRankMathTwitterTitle'),
            99
        );
        add_filter(
            'rank_math/opengraph/twitter/twitter_description',
            array(self::class, 'filterRankMathTwitterDescription'),
            99
        );
        add_filter(
            'rank_math/opengraph/twitter/card_type',
            array(self::class, 'filterRankMathTwitterCard'),
            99
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

    public static function filterRankMathFacebookTitle(mixed $title): mixed
    {
        if (! is_front_page()) {
            return $title;
        }

        self::$rankMathFacebookHandled = true;

        return self::homeTitle();
    }

    public static function filterRankMathFacebookDescription(
        mixed $description
    ): mixed {
        return is_front_page() ? self::HOME_DESCRIPTION : $description;
    }

    public static function filterRankMathFacebookType(mixed $type): mixed
    {
        return is_front_page() ? 'website' : $type;
    }

    public static function filterRankMathFacebookUrl(mixed $url): mixed
    {
        return is_front_page() ? home_url('/') : $url;
    }

    public static function filterRankMathFacebookSiteName(mixed $name): mixed
    {
        return is_front_page() ? (string) get_bloginfo('name') : $name;
    }

    public static function filterRankMathFacebookLocale(mixed $locale): mixed
    {
        return is_front_page() ? (string) get_locale() : $locale;
    }

    public static function filterRankMathTwitterTitle(mixed $title): mixed
    {
        if (! is_front_page()) {
            return $title;
        }

        self::$rankMathTwitterHandled = true;

        return self::homeTitle();
    }

    public static function filterRankMathTwitterDescription(
        mixed $description
    ): mixed {
        return is_front_page() ? self::HOME_DESCRIPTION : $description;
    }

    public static function filterRankMathTwitterCard(mixed $card): mixed
    {
        return is_front_page() ? 'summary' : $card;
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

        if (! self::$rankMathFacebookHandled) {
            self::renderMeta('property', 'og:title', self::homeTitle());
            self::renderMeta('property', 'og:type', 'website');
            self::renderMeta('property', 'og:url', home_url('/'));
            self::renderMeta(
                'property',
                'og:description',
                self::HOME_DESCRIPTION
            );
            self::renderMeta(
                'property',
                'og:site_name',
                (string) get_bloginfo('name')
            );
            self::renderMeta('property', 'og:locale', (string) get_locale());
        }

        if (! self::$rankMathTwitterHandled) {
            self::renderMeta('name', 'twitter:card', 'summary');
            self::renderMeta('name', 'twitter:title', self::homeTitle());
            self::renderMeta(
                'name',
                'twitter:description',
                self::HOME_DESCRIPTION
            );
        }
    }

    private static function renderMeta(
        string $attribute,
        string $name,
        string $content
    ): void {
        printf(
            '<meta %s="%s" content="%s">' . "\n",
            esc_attr($attribute),
            esc_attr($name),
            esc_attr($content)
        );
    }

    private static function homeTitle(): string
    {
        $name = (string) get_bloginfo('name');
        $tagline = (string) get_bloginfo('description');

        return trim($name . ($tagline !== '' ? ': ' . $tagline : ''));
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
