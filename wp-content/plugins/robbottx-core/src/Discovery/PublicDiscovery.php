<?php

declare(strict_types=1);

namespace RobbottX\Core\Discovery;

final class PublicDiscovery
{
    private const RETIRED_POST_TYPE = 'robot';
    private const INACTIVE_COMMERCE_POST_TYPE = 'product';
    private const INACTIVE_COMMERCE_TAXONOMIES = array(
        'product_cat',
        'product_tag',
        'product_brand',
        'product_shipping_class',
        'product_type',
        'product_visibility',
    );

    /**
     * @var array<string, list<int>>
     */
    private static array $contentIdCache = array();

    private static ?int $excludedCategoryIdCache = null;

    /**
     * @var array<string, list<string>>
     */
    private const EXCLUDED_CONTENT = array(
        'post' => array('hello-world'),
        'page' => array(
            'sample-page',
            'robots-catalog',
            'shop',
            'cart',
            'checkout',
            'my-account',
        ),
    );

    private const EXCLUDED_CATEGORY = 'uncategorized';
    private const RETIRED_REQUEST_FLAG = '_robbottx_retired_request';

    public static function boot(): void
    {
        add_filter(
            'wp_sitemaps_post_types',
            array(self::class, 'filterSitemapPostTypes')
        );
        add_filter(
            'wp_sitemaps_posts_query_args',
            array(self::class, 'filterSitemapPostQueryArgs'),
            10,
            2
        );
        add_filter(
            'wp_sitemaps_taxonomies_query_args',
            array(self::class, 'filterSitemapTaxonomyQueryArgs'),
            10,
            2
        );
        add_filter(
            'wp_sitemaps_taxonomies',
            array(self::class, 'filterSitemapTaxonomies')
        );
        add_filter(
            'wp_sitemaps_add_provider',
            array(self::class, 'filterSitemapProvider'),
            10,
            2
        );
        add_filter(
            'rank_math/sitemap/exclude_post_type',
            array(self::class, 'filterRankMathSitemapPostType'),
            10,
            2
        );
        add_filter(
            'rank_math/sitemap/exclude_taxonomy',
            array(self::class, 'filterRankMathSitemapTaxonomy'),
            10,
            2
        );
        add_filter(
            'rank_math/sitemap/html_sitemap_post_types',
            array(self::class, 'filterRankMathHtmlSitemapPostTypes')
        );
        add_filter(
            'rank_math/sitemap/html_sitemap_taxonomies',
            array(self::class, 'filterRankMathHtmlSitemapTaxonomies')
        );

        add_action('pre_get_posts', array(self::class, 'filterMainQuery'));
        add_action(
            'wp_loaded',
            array(self::class, 'blockClassicCommerceRequest'),
            -PHP_INT_MAX
        );
        add_action(
            'template_redirect',
            array(self::class, 'retireFrontendRequest'),
            0
        );
        add_filter(
            'redirect_canonical',
            array(self::class, 'filterCanonicalRedirect'),
            PHP_INT_MAX,
            2
        );
        add_filter(
            'old_slug_redirect_post_id',
            array(self::class, 'filterOldSlugRedirectPostId'),
            PHP_INT_MAX
        );
        add_filter(
            'old_slug_redirect_url',
            array(self::class, 'filterOldSlugRedirectUrl'),
            PHP_INT_MAX
        );
        add_filter('wp_robots', array(self::class, 'filterRobots'), 30);
        add_filter(
            'rank_math/frontend/robots',
            array(self::class, 'filterRankMathRobots'),
            30
        );

        add_filter(
            'rest_post_search_query',
            array(self::class, 'filterRestPostSearchQuery'),
            10,
            2
        );
        add_filter(
            'rest_post_query',
            array(self::class, 'filterRestPostQuery'),
            10,
            2
        );
        add_filter(
            'rest_page_query',
            array(self::class, 'filterRestPageQuery'),
            10,
            2
        );
        add_filter(
            'rest_robot_query',
            array(self::class, 'filterRestRobotQuery'),
            10,
            2
        );
        add_filter(
            'rest_product_query',
            array(self::class, 'filterRestProductQuery'),
            10,
            2
        );
        add_filter(
            'rest_product_cat_query',
            array(self::class, 'filterRestProductTaxonomyQuery'),
            10,
            2
        );
        add_filter(
            'rest_product_tag_query',
            array(self::class, 'filterRestProductTaxonomyQuery'),
            10,
            2
        );
        add_filter(
            'rest_product_brand_query',
            array(self::class, 'filterRestProductTaxonomyQuery'),
            10,
            2
        );
        add_action(
            'init',
            array(self::class, 'registerInactiveCommerceRestFilters'),
            PHP_INT_MAX
        );
        add_filter(
            'rest_term_search_query',
            array(self::class, 'filterRestTermSearchQuery'),
            10,
            2
        );
        add_filter(
            'rest_category_query',
            array(self::class, 'filterRestCategoryQuery'),
            10,
            2
        );
        add_filter(
            'rest_user_query',
            array(self::class, 'filterRestUserQuery'),
            10,
            2
        );
        add_filter(
            'rest_pre_dispatch',
            array(self::class, 'filterRestDetailResponse'),
            10,
            3
        );

        add_filter(
            'wp_list_pages_excludes',
            array(self::class, 'filterPageListExcludes')
        );
        add_filter(
            'widget_posts_args',
            array(self::class, 'filterRecentPostsArguments'),
            10,
            2
        );
        add_filter(
            'widget_categories_args',
            array(self::class, 'filterCategoryListArguments'),
            10,
            2
        );
        add_filter(
            'widget_categories_dropdown_args',
            array(self::class, 'filterCategoryListArguments'),
            10,
            2
        );
        add_filter(
            'wp_list_authors_args',
            array(self::class, 'filterAuthorListArguments'),
            10,
            2
        );
        add_filter(
            'wp_get_nav_menu_items',
            array(self::class, 'filterNavigationItems'),
            10,
            3
        );
    }

    /**
     * @param array<string, mixed> $postTypes
     * @return array<string, mixed>
     */
    public static function filterSitemapPostTypes(array $postTypes): array
    {
        unset($postTypes[self::RETIRED_POST_TYPE]);
        unset($postTypes[self::INACTIVE_COMMERCE_POST_TYPE]);

        return $postTypes;
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterSitemapPostQueryArgs(
        array $arguments,
        string $postType
    ): array {
        if (
            in_array(
                $postType,
                array(
                    self::RETIRED_POST_TYPE,
                    self::INACTIVE_COMMERCE_POST_TYPE,
                ),
                true
            )
        ) {
            return self::forceNoPostResults($arguments);
        }

        return self::excludeContentIds(
            $arguments,
            self::contentIdsForPostType($postType)
        );
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterSitemapTaxonomyQueryArgs(
        array $arguments,
        string $taxonomy
    ): array {
        if (self::isInactiveCommerceTaxonomy($taxonomy)) {
            return self::forceNoTermResults($arguments);
        }

        if ($taxonomy !== 'category') {
            return $arguments;
        }

        return self::excludeTermId($arguments);
    }

    /**
     * @param array<string, mixed> $taxonomies
     * @return array<string, mixed>
     */
    public static function filterSitemapTaxonomies(
        array $taxonomies
    ): array {
        foreach (array_keys($taxonomies) as $taxonomy) {
            if (self::isInactiveCommerceTaxonomy((string) $taxonomy)) {
                unset($taxonomies[$taxonomy]);
            }
        }

        return $taxonomies;
    }

    public static function filterSitemapProvider(
        mixed $provider,
        string $name
    ): mixed {
        return $name === 'users' ? false : $provider;
    }

    public static function filterRankMathSitemapPostType(
        mixed $excluded,
        string $postType
    ): bool {
        return (bool) $excluded
            || in_array(
                $postType,
                array(
                    self::RETIRED_POST_TYPE,
                    self::INACTIVE_COMMERCE_POST_TYPE,
                ),
                true
            );
    }

    public static function filterRankMathSitemapTaxonomy(
        mixed $excluded,
        string $taxonomy
    ): bool {
        return (bool) $excluded
            || self::isInactiveCommerceTaxonomy($taxonomy);
    }

    /**
     * @param array<int|string, mixed> $postTypes
     * @return array<int|string, mixed>
     */
    public static function filterRankMathHtmlSitemapPostTypes(
        array $postTypes
    ): array {
        $wasList = array_is_list($postTypes);

        foreach ($postTypes as $key => $value) {
            $name = self::namedItemName($key, $value);

            if (
                in_array(
                    $name,
                    array(
                        self::RETIRED_POST_TYPE,
                        self::INACTIVE_COMMERCE_POST_TYPE,
                    ),
                    true
                )
            ) {
                unset($postTypes[$key]);
            }
        }

        return $wasList ? array_values($postTypes) : $postTypes;
    }

    /**
     * @param array<int|string, mixed> $taxonomies
     * @return array<int|string, mixed>
     */
    public static function filterRankMathHtmlSitemapTaxonomies(
        array $taxonomies
    ): array {
        $wasList = array_is_list($taxonomies);

        foreach ($taxonomies as $key => $value) {
            if (
                self::isInactiveCommerceTaxonomy(
                    self::namedItemName($key, $value)
                )
            ) {
                unset($taxonomies[$key]);
            }
        }

        return $wasList ? array_values($taxonomies) : $taxonomies;
    }

    public static function filterMainQuery(object $query): void
    {
        if (
            is_admin()
            || self::canEditHiddenContent()
            || ! method_exists($query, 'is_main_query')
            || ! $query->is_main_query()
        ) {
            return;
        }

        $isSearch         = self::queryFlag($query, 'is_search');
        $isFeed           = self::queryFlag($query, 'is_feed');
        $isHome           = self::queryFlag($query, 'is_home');
        $isDate           = self::queryFlag($query, 'is_date');
        $isAuthor         = self::queryFlag($query, 'is_author');
        $isHiddenCategory = self::isExcludedCategoryQuery($query);
        $isRetiredArchive = method_exists($query, 'is_post_type_archive')
            && $query->is_post_type_archive(self::RETIRED_POST_TYPE);
        $isInactiveCommerceArchive = method_exists(
            $query,
            'is_post_type_archive'
        ) && $query->is_post_type_archive(
            self::INACTIVE_COMMERCE_POST_TYPE
        );
        $isInactiveCommerceTaxonomy = self::isInactiveCommerceTaxonomyQuery(
            $query
        );

        if (
            $isAuthor
            || $isHiddenCategory
            || $isRetiredArchive
            || $isInactiveCommerceArchive
            || $isInactiveCommerceTaxonomy
        ) {
            self::forceQueryNoResults($query);
            return;
        }

        if (! $isSearch && ! $isFeed && ! $isHome && ! $isDate) {
            return;
        }

        self::excludeIdsFromQuery($query, self::excludedContentIds());

        if ($isSearch || $isFeed) {
            self::excludeHiddenPostTypes($query, $isSearch);
        }
    }

    public static function blockClassicCommerceRequest(): void
    {
        if (
            is_admin()
            || self::canEditHiddenContent()
            || ! self::isClassicCommerceRequest()
        ) {
            return;
        }

        status_header(404);
        nocache_headers();
        wp_die(
            esc_html__('Not found.', 'robbottx-core'),
            esc_html__('Page not found.', 'robbottx-core'),
            array('response' => 404)
        );
    }

    public static function retireFrontendRequest(): void
    {
        if (
            is_admin()
            || self::canEditHiddenContent()
            || ! self::isExcludedFrontendRequest()
        ) {
            return;
        }

        global $wp_query;

        if (
            ! is_object($wp_query)
            || ! method_exists($wp_query, 'set')
            || ! method_exists($wp_query, 'set_404')
        ) {
            status_header(410);
            nocache_headers();
            wp_die(
                esc_html__(
                    'This address is no longer available.',
                    'robbottx-core'
                ),
                esc_html__('Page not found.', 'robbottx-core'),
                array('response' => 410)
            );

            return;
        }

        $wp_query->set(self::RETIRED_REQUEST_FLAG, true);
        $wp_query->set_404();
        status_header(410);
        nocache_headers();
    }

    public static function filterCanonicalRedirect(
        mixed $redirectUrl,
        mixed $requestedUrl
    ): mixed {
        return self::isRetiredQueryFlagged() ? false : $redirectUrl;
    }

    public static function filterOldSlugRedirectPostId(
        mixed $postId
    ): mixed {
        return self::isRetiredQueryFlagged() ? 0 : $postId;
    }

    public static function filterOldSlugRedirectUrl(
        mixed $redirectUrl
    ): mixed {
        return self::isRetiredQueryFlagged() ? false : $redirectUrl;
    }

    /**
     * @param array<string, bool|string> $robots
     * @return array<string, bool|string>
     */
    public static function filterRobots(array $robots): array
    {
        if (! self::isExcludedFrontendRequest()) {
            return $robots;
        }

        unset($robots['index'], $robots['nofollow']);
        $robots['noindex'] = true;
        $robots['follow']  = true;

        return $robots;
    }

    /**
     * @param array<string, string> $robots
     * @return array<string, string>
     */
    public static function filterRankMathRobots(array $robots): array
    {
        if (! self::isExcludedFrontendRequest()) {
            return $robots;
        }

        unset($robots['index'], $robots['nofollow']);
        $robots['noindex'] = 'noindex';
        $robots['follow']  = 'follow';

        return $robots;
    }

    public static function filterRestDetailResponse(
        mixed $result,
        mixed $server,
        mixed $request
    ): mixed {
        if (
            ! is_object($request)
            || ! method_exists($request, 'get_method')
            || ! method_exists($request, 'get_route')
        ) {
            return $result;
        }

        $method = strtoupper((string) $request->get_method());
        $route  = rtrim((string) $request->get_route(), '/');

        if (
            ! self::canEditHiddenContent()
            && preg_match('#^/wc/store(?:/|$)#', $route) === 1
        ) {
            return new \WP_Error(
                'rest_not_found',
                'Not found.',
                array('status' => 404)
            );
        }

        if (! in_array($method, array('GET', 'HEAD'), true)) {
            return $result;
        }

        if (
            preg_match(
                '#^/wp/v2/([a-z0-9_-]+)/([0-9]+)$#i',
                $route,
                $matches
            ) !== 1
        ) {
            return $result;
        }

        $resource = strtolower($matches[1]);
        $resourceId = (int) $matches[2];

        if (! self::isBlockedRestDetail($resource, $resourceId)) {
            return $result;
        }

        return new \WP_Error(
            'rest_not_found',
            'Not found.',
            array('status' => 404)
        );
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterRestPostSearchQuery(
        array $arguments,
        mixed $request
    ): array {
        if (self::canEditHiddenContent()) {
            return $arguments;
        }

        $arguments = self::excludeContentIds(
            $arguments,
            self::excludedContentIds()
        );

        $postTypes = $arguments['post_type'] ?? array();

        if ($postTypes === '' || $postTypes === 'any' || $postTypes === array()) {
            $postTypes = self::publicSearchPostTypes(true);
        }

        $filtered = self::withoutHiddenPostTypes($postTypes);

        if ($filtered === array()) {
            return self::forceNoPostResults($arguments);
        }

        $arguments['post_type'] = $filtered;

        return $arguments;
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterRestPostQuery(
        array $arguments,
        mixed $request
    ): array {
        return self::filterPublicRestPostType(
            $arguments,
            'post'
        );
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterRestPageQuery(
        array $arguments,
        mixed $request
    ): array {
        return self::filterPublicRestPostType(
            $arguments,
            'page'
        );
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterRestRobotQuery(
        array $arguments,
        mixed $request
    ): array {
        return self::canEditHiddenContent()
            ? $arguments
            : self::forceNoPostResults($arguments);
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterRestProductQuery(
        array $arguments,
        mixed $request
    ): array {
        return self::canEditHiddenContent()
            ? $arguments
            : self::forceNoPostResults($arguments);
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterRestProductTaxonomyQuery(
        array $arguments,
        mixed $request
    ): array {
        return self::canEditHiddenContent()
            ? $arguments
            : self::forceNoTermResults($arguments);
    }

    public static function registerInactiveCommerceRestFilters(): void
    {
        foreach (self::inactiveCommerceTaxonomies() as $taxonomy) {
            add_filter(
                'rest_' . $taxonomy . '_query',
                array(self::class, 'filterRestProductTaxonomyQuery'),
                10,
                2
            );
        }
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterRestTermSearchQuery(
        array $arguments,
        mixed $request
    ): array {
        return self::canEditHiddenContent()
            ? $arguments
            : self::excludeTermId($arguments);
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterRestCategoryQuery(
        array $arguments,
        mixed $request
    ): array {
        return self::canEditHiddenContent()
            ? $arguments
            : self::excludeTermId($arguments);
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    public static function filterRestUserQuery(
        array $arguments,
        mixed $request
    ): array {
        if (self::canEditHiddenContent()) {
            return $arguments;
        }

        $arguments['include'] = array(0);

        return $arguments;
    }

    /**
     * @param list<int|string> $excluded
     * @return list<int>
     */
    public static function filterPageListExcludes(array $excluded): array
    {
        if (is_admin() || self::canEditHiddenContent()) {
            return array_values($excluded);
        }

        return self::mergeIds(
            $excluded,
            self::contentIdsForPostType('page')
        );
    }

    /**
     * @param array<string, mixed> $arguments
     * @param array<string, mixed> $instance
     * @return array<string, mixed>
     */
    public static function filterRecentPostsArguments(
        array $arguments,
        array $instance = array()
    ): array {
        if (is_admin() || self::canEditHiddenContent()) {
            return $arguments;
        }

        return self::excludeContentIds(
            $arguments,
            self::contentIdsForPostType('post')
        );
    }

    /**
     * @param array<string, mixed> $arguments
     * @param array<string, mixed> $instance
     * @return array<string, mixed>
     */
    public static function filterCategoryListArguments(
        array $arguments,
        array $instance = array()
    ): array {
        return is_admin() || self::canEditHiddenContent()
            ? $arguments
            : self::excludeTermId($arguments);
    }

    /**
     * @param array<string, mixed> $arguments
     * @param array<string, mixed> $parsedArguments
     * @return array<string, mixed>
     */
    public static function filterAuthorListArguments(
        array $arguments,
        array $parsedArguments = array()
    ): array {
        if (is_admin() || self::canEditHiddenContent()) {
            return $arguments;
        }

        $arguments['include'] = array(0);

        return $arguments;
    }

    /**
     * @param list<object> $items
     * @param array<string, mixed> $arguments
     * @return list<object>
     */
    public static function filterNavigationItems(
        array $items,
        mixed $menu = null,
        array $arguments = array()
    ): array {
        if (is_admin() || self::canEditHiddenContent()) {
            return array_values($items);
        }

        $excludedContentIds = self::excludedContentIds();
        $excludedTermId     = self::excludedCategoryId();

        return array_values(
            array_filter(
                $items,
                static function (object $item) use (
                    $excludedContentIds,
                    $excludedTermId
                ): bool {
                    $type     = (string) ($item->type ?? '');
                    $object   = (string) ($item->object ?? '');
                    $objectId = (int) ($item->object_id ?? 0);

                    if (
                        in_array(
                            $object,
                            array(
                                self::RETIRED_POST_TYPE,
                                self::INACTIVE_COMMERCE_POST_TYPE,
                            ),
                            true
                        )
                        && in_array(
                            $type,
                            array('post_type', 'post_type_archive'),
                            true
                        )
                    ) {
                        return false;
                    }

                    if (
                        $type === 'post_type'
                        && in_array($objectId, $excludedContentIds, true)
                    ) {
                        return false;
                    }

                    if (
                        $type === 'taxonomy'
                        && (
                            (
                                $object === 'category'
                                && $excludedTermId > 0
                                && $objectId === $excludedTermId
                            )
                            || self::isInactiveCommerceTaxonomy($object)
                        )
                    ) {
                        return false;
                    }

                    return ! self::isExcludedCustomLink(
                        (string) ($item->url ?? '')
                    );
                }
            )
        );
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    private static function filterPublicRestPostType(
        array $arguments,
        string $postType
    ): array {
        if (self::canEditHiddenContent()) {
            return $arguments;
        }

        return self::excludeContentIds(
            $arguments,
            self::contentIdsForPostType($postType)
        );
    }

    private static function canEditHiddenContent(): bool
    {
        return current_user_can('edit_others_posts');
    }

    private static function isBlockedRestDetail(
        string $resource,
        int $resourceId
    ): bool {
        if (
            in_array(
                $resource,
                array(
                    self::RETIRED_POST_TYPE,
                    self::INACTIVE_COMMERCE_POST_TYPE,
                ),
                true
            )
        ) {
            return ! current_user_can('edit_post', $resourceId);
        }

        if (self::isInactiveCommerceRestResource($resource)) {
            return ! self::canEditHiddenContent();
        }

        if ($resource === 'posts') {
            return in_array(
                $resourceId,
                self::contentIdsForPostType('post'),
                true
            ) && ! current_user_can('edit_post', $resourceId);
        }

        if ($resource === 'pages') {
            return in_array(
                $resourceId,
                self::contentIdsForPostType('page'),
                true
            ) && ! current_user_can('edit_post', $resourceId);
        }

        if ($resource === 'categories') {
            return $resourceId === self::excludedCategoryId()
                && ! current_user_can('manage_categories');
        }

        return $resource === 'users'
            && ! current_user_can('list_users');
    }

    private static function queryFlag(object $query, string $method): bool
    {
        return method_exists($query, $method) && (bool) $query->{$method}();
    }

    private static function isExcludedCategoryQuery(object $query): bool
    {
        if (
            method_exists($query, 'is_category')
            && $query->is_category(self::EXCLUDED_CATEGORY)
        ) {
            return true;
        }

        if (! method_exists($query, 'get')) {
            return false;
        }

        $categoryName = (string) $query->get('category_name');

        if ($categoryName === self::EXCLUDED_CATEGORY) {
            return true;
        }

        $categoryId = (int) $query->get('cat');

        return $categoryId > 0 && $categoryId === self::excludedCategoryId();
    }

    private static function namedItemName(
        int|string $key,
        mixed $value
    ): string {
        if (is_string($key)) {
            return $key;
        }

        if (is_string($value)) {
            return $value;
        }

        return is_object($value)
            ? (string) ($value->name ?? '')
            : '';
    }

    private static function isInactiveCommerceTaxonomyQuery(
        object $query
    ): bool {
        return method_exists($query, 'is_tax')
            && (bool) $query->is_tax(self::inactiveCommerceTaxonomies());
    }

    private static function forceQueryNoResults(object $query): void
    {
        if (method_exists($query, 'set')) {
            $query->set('post__in', array(0));
        }
    }

    /**
     * @param list<int> $ids
     */
    private static function excludeIdsFromQuery(object $query, array $ids): void
    {
        if ($ids === array() || ! method_exists($query, 'get')) {
            return;
        }

        $included = self::withoutExcludedIds($query->get('post__in'), $ids);

        if ($included !== null) {
            $query->set('post__in', $included);
            return;
        }

        $existing = $query->get('post__not_in');
        $query->set('post__not_in', self::mergeIds($existing, $ids));
    }

    private static function excludeHiddenPostTypes(
        object $query,
        bool $isSearch
    ): void {
        if (! method_exists($query, 'get') || ! method_exists($query, 'set')) {
            return;
        }

        $postTypes = $query->get('post_type');

        if ($postTypes === '' || $postTypes === null) {
            if (! $isSearch) {
                return;
            }

            $postTypes = self::publicSearchPostTypes(false);
        } elseif ($postTypes === 'any') {
            $postTypes = self::publicSearchPostTypes(false);
        } elseif (is_string($postTypes)) {
            if (
                in_array(
                    $postTypes,
                    array(
                        self::RETIRED_POST_TYPE,
                        self::INACTIVE_COMMERCE_POST_TYPE,
                    ),
                    true
                )
            ) {
                self::forceQueryNoResults($query);
            }

            return;
        }

        $filtered = self::withoutHiddenPostTypes($postTypes);

        if ($filtered === array()) {
            self::forceQueryNoResults($query);
            return;
        }

        $query->set('post_type', $filtered);
    }

    /**
     * @return list<string>
     */
    private static function publicSearchPostTypes(bool $restOnly): array
    {
        $requirements = array(
            'public'              => true,
            'exclude_from_search' => false,
        );

        if ($restOnly) {
            $requirements['show_in_rest'] = true;
        }

        $postTypes = get_post_types($requirements, 'names');

        return array_values(
            array_diff(
                array_map('strval', (array) $postTypes),
                array(
                    self::RETIRED_POST_TYPE,
                    self::INACTIVE_COMMERCE_POST_TYPE,
                )
            )
        );
    }

    /**
     * @return list<string>
     */
    private static function withoutHiddenPostTypes(mixed $postTypes): array
    {
        $postTypes = is_array($postTypes) ? $postTypes : array($postTypes);

        return array_values(
            array_filter(
                array_map('strval', $postTypes),
                static fn (string $postType): bool => $postType !== ''
                    && ! in_array(
                        $postType,
                        array(
                            self::RETIRED_POST_TYPE,
                            self::INACTIVE_COMMERCE_POST_TYPE,
                        ),
                        true
                    )
            )
        );
    }

    /**
     * @param array<string, mixed> $arguments
     * @param list<int> $ids
     * @return array<string, mixed>
     */
    private static function excludeContentIds(
        array $arguments,
        array $ids
    ): array {
        if ($ids === array()) {
            return $arguments;
        }

        $included = self::withoutExcludedIds(
            $arguments['post__in'] ?? array(),
            $ids
        );

        if ($included !== null) {
            $arguments['post__in'] = $included;
            return $arguments;
        }

        $arguments['post__not_in'] = self::mergeIds(
            $arguments['post__not_in'] ?? array(),
            $ids
        );

        return $arguments;
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    private static function excludeTermId(array $arguments): array
    {
        $termId = self::excludedCategoryId();

        if ($termId <= 0) {
            return $arguments;
        }

        $included = self::withoutExcludedIds(
            $arguments['include'] ?? array(),
            array($termId)
        );

        if ($included !== null) {
            $arguments['include'] = $included;
            return $arguments;
        }

        $arguments['exclude'] = self::mergeIds(
            $arguments['exclude'] ?? array(),
            array($termId)
        );

        return $arguments;
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    private static function forceNoPostResults(array $arguments): array
    {
        $arguments['post__in'] = array(0);

        return $arguments;
    }

    /**
     * @param array<string, mixed> $arguments
     * @return array<string, mixed>
     */
    private static function forceNoTermResults(array $arguments): array
    {
        $arguments['include'] = array(0);

        return $arguments;
    }

    /**
     * @return list<int>
     */
    private static function excludedContentIds(): array
    {
        $ids = array();

        foreach (array_keys(self::EXCLUDED_CONTENT) as $postType) {
            $ids = array_merge(
                $ids,
                self::contentIdsForPostType($postType)
            );
        }

        return self::mergeIds(array(), $ids);
    }

    /**
     * @return list<int>
     */
    private static function contentIdsForPostType(string $postType): array
    {
        if (array_key_exists($postType, self::$contentIdCache)) {
            return self::$contentIdCache[$postType];
        }

        $ids = array();

        foreach (self::EXCLUDED_CONTENT[$postType] ?? array() as $slug) {
            $post = get_page_by_path($slug, OBJECT, $postType);

            if (is_object($post) && isset($post->ID)) {
                $ids[] = (int) $post->ID;
            }
        }

        self::$contentIdCache[$postType] = self::mergeIds(array(), $ids);

        return self::$contentIdCache[$postType];
    }

    private static function excludedCategoryId(): int
    {
        if (self::$excludedCategoryIdCache !== null) {
            return self::$excludedCategoryIdCache;
        }

        $term = get_term_by('slug', self::EXCLUDED_CATEGORY, 'category');

        self::$excludedCategoryIdCache = is_object($term) && isset($term->term_id)
            ? (int) $term->term_id
            : 0;

        return self::$excludedCategoryIdCache;
    }

    /**
     * @return list<string>
     */
    private static function inactiveCommerceTaxonomies(): array
    {
        if (function_exists('get_object_taxonomies')) {
            $taxonomies = array_values(
                array_unique(
                    array_filter(
                        array_map(
                            'strval',
                            (array) get_object_taxonomies(
                                self::INACTIVE_COMMERCE_POST_TYPE,
                                'names'
                            )
                        ),
                        static fn (string $taxonomy): bool => $taxonomy !== ''
                    )
                )
            );

            if ($taxonomies !== array()) {
                return $taxonomies;
            }
        }

        return self::INACTIVE_COMMERCE_TAXONOMIES;
    }

    private static function isInactiveCommerceTaxonomy(
        string $taxonomy
    ): bool {
        return in_array(
            $taxonomy,
            self::inactiveCommerceTaxonomies(),
            true
        ) || str_starts_with($taxonomy, 'pa_');
    }

    private static function isInactiveCommerceRestResource(
        string $resource
    ): bool {
        if (self::isInactiveCommerceTaxonomy($resource)) {
            return true;
        }

        foreach (self::inactiveCommerceTaxonomies() as $taxonomy) {
            if (! function_exists('get_taxonomy')) {
                continue;
            }

            $taxonomyObject = get_taxonomy($taxonomy);
            $restBase = is_object($taxonomyObject)
                ? (string) ($taxonomyObject->rest_base ?? '')
                : '';

            if ($restBase !== '' && strtolower($restBase) === $resource) {
                return true;
            }
        }

        return false;
    }

    private static function isClassicCommerceRequest(): bool
    {
        foreach (array('wc-ajax', 'add-to-cart') as $requestKey) {
            if (
                array_key_exists($requestKey, $_GET)
                || array_key_exists($requestKey, $_POST)
                || array_key_exists($requestKey, $_REQUEST)
            ) {
                return true;
            }
        }

        return false;
    }

    private static function isInactiveCommerceTaxonomyPath(
        string $path
    ): bool {
        $rewriteSlugs = array(
            'product-category',
            'product-tag',
            'product-brand',
        );

        if (function_exists('get_taxonomy')) {
            foreach (self::inactiveCommerceTaxonomies() as $taxonomy) {
                $taxonomyObject = get_taxonomy($taxonomy);
                $rewrite = is_object($taxonomyObject)
                    ? ($taxonomyObject->rewrite ?? null)
                    : null;
                $rewriteSlug = is_array($rewrite)
                    ? (string) ($rewrite['slug'] ?? '')
                    : (is_string($rewrite) ? $rewrite : '');

                if ($rewriteSlug !== '') {
                    $rewriteSlugs[] = trim($rewriteSlug, '/');
                }
            }
        }

        foreach (array_unique($rewriteSlugs) as $rewriteSlug) {
            if (
                $rewriteSlug !== ''
                && preg_match(
                    '#(?:^|/)'
                    . preg_quote($rewriteSlug, '#')
                    . '(?:/|$)#',
                    $path
                ) === 1
            ) {
                return true;
            }
        }

        return false;
    }

    private static function isExcludedFrontendRequest(): bool
    {
        if (self::isRetiredQueryFlagged()) {
            return true;
        }

        return is_singular(self::RETIRED_POST_TYPE)
            || is_singular(self::INACTIVE_COMMERCE_POST_TYPE)
            || is_post_type_archive(self::RETIRED_POST_TYPE)
            || is_post_type_archive(self::INACTIVE_COMMERCE_POST_TYPE)
            || is_tax(self::inactiveCommerceTaxonomies())
            || is_page(self::EXCLUDED_CONTENT['page'])
            || is_single(self::EXCLUDED_CONTENT['post'])
            || is_category(self::EXCLUDED_CATEGORY)
            || is_author();
    }

    private static function isRetiredQueryFlagged(): bool
    {
        global $wp_query;

        return is_object($wp_query)
            && method_exists($wp_query, 'get')
            && (bool) $wp_query->get(self::RETIRED_REQUEST_FLAG);
    }

    /**
     * @param mixed $existing
     * @param list<int> $additional
     * @return list<int>
     */
    private static function mergeIds(mixed $existing, array $additional): array
    {
        if (is_string($existing)) {
            $existing = preg_split('/\s*,\s*/', $existing, -1, PREG_SPLIT_NO_EMPTY);
        }

        if (! is_array($existing)) {
            $existing = $existing === null || $existing === ''
                ? array()
                : array($existing);
        }

        $ids = array_map('intval', array_merge($existing, $additional));
        $ids = array_filter($ids, static fn (int $id): bool => $id >= 0);

        return array_values(array_unique($ids));
    }

    /**
     * @param mixed $included
     * @param list<int> $excluded
     * @return list<int>|null
     */
    private static function withoutExcludedIds(
        mixed $included,
        array $excluded
    ): ?array {
        $includedIds = self::mergeIds($included, array());

        if ($includedIds === array()) {
            return null;
        }

        $remaining = array_values(array_diff($includedIds, $excluded));

        return $remaining === array() ? array(0) : $remaining;
    }

    private static function isExcludedCustomLink(string $url): bool
    {
        if ($url === '') {
            return false;
        }

        $urlHost  = parse_url($url, PHP_URL_HOST);
        $siteHost = parse_url(home_url('/'), PHP_URL_HOST);

        if (
            is_string($urlHost)
            && $urlHost !== ''
            && is_string($siteHost)
            && strcasecmp($urlHost, $siteHost) !== 0
        ) {
            return false;
        }

        $path = trim((string) parse_url($url, PHP_URL_PATH), '/');

        if ($path === '') {
            return false;
        }

        return preg_match(
            '#(?:^|/)(?:robots-catalog|sample-page|hello-world|shop|cart|checkout|my-account)(?:/|$)#',
            $path
        ) === 1
            || preg_match(
                '#(?:^|/)(?:robot|robots|product)(?:/|$)#',
                $path
            ) === 1
            || preg_match(
                '#(?:^|/)category/uncategorized$#',
                $path
            ) === 1
            || self::isInactiveCommerceTaxonomyPath($path)
            || preg_match('#(?:^|/)author/[^/]+$#', $path) === 1;
    }
}
