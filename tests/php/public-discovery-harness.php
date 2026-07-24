<?php

declare(strict_types=1);

const OBJECT = 'OBJECT';

$GLOBALS['rbtx_admin']      = false;
$GLOBALS['rbtx_can_edit']   = false;
$GLOBALS['rbtx_hooks']      = array();
$GLOBALS['rbtx_request']    = array();
$GLOBALS['rbtx_assertions'] = 0;
$GLOBALS['rbtx_post_lookups'] = 0;
$GLOBALS['rbtx_term_lookups'] = 0;
$GLOBALS['rbtx_caps'] = array();
$GLOBALS['rbtx_status_headers'] = array();
$GLOBALS['rbtx_nocache_headers'] = 0;
$GLOBALS['rbtx_wp_die_calls'] = array();

final class WP_Error
{
    /**
     * @param array<string, mixed> $data
     */
    public function __construct(
        public string $code,
        public string $message,
        public array $data = array()
    ) {
    }
}

function add_filter(
    string $hook,
    callable|array|string $callback,
    int $priority = 10,
    int $acceptedArgs = 1
): void {
    $GLOBALS['rbtx_hooks'][$hook] = array(
        'callback' => $callback,
        'priority' => $priority,
        'accepted_args' => $acceptedArgs,
    );
}

function add_action(
    string $hook,
    callable|array|string $callback,
    int $priority = 10,
    int $acceptedArgs = 1
): void {
    add_filter($hook, $callback, $priority, $acceptedArgs);
}

function is_admin(): bool
{
    return $GLOBALS['rbtx_admin'];
}

function current_user_can(string $capability, mixed ...$arguments): bool
{
    if ($capability === 'edit_others_posts') {
        return $GLOBALS['rbtx_can_edit'];
    }

    $key = $capability;

    if ($arguments !== array()) {
        $key .= ':' . implode(
            ',',
            array_map('strval', $arguments)
        );
    }

    return in_array($key, $GLOBALS['rbtx_caps'], true);
}

function get_page_by_path(
    string $slug,
    string $output = OBJECT,
    string $postType = 'page'
): ?object {
    ++$GLOBALS['rbtx_post_lookups'];

    $ids = array(
        'post:hello-world' => 101,
        'page:sample-page' => 201,
        'page:robots-catalog' => 202,
        'page:shop' => 29,
        'page:cart' => 30,
        'page:checkout' => 31,
        'page:my-account' => 32,
    );
    $key = $postType . ':' . $slug;

    return isset($ids[$key]) ? (object) array('ID' => $ids[$key]) : null;
}

function get_term_by(
    string $field,
    string $value,
    string $taxonomy
): object|false {
    ++$GLOBALS['rbtx_term_lookups'];

    if (
        $field === 'slug'
        && $value === 'uncategorized'
        && $taxonomy === 'category'
    ) {
        return (object) array('term_id' => 301);
    }

    return false;
}

/**
 * @param array<string, mixed> $arguments
 * @return list<string>
 */
function get_post_types(array $arguments, string $output): array
{
    return array(
        'post',
        'page',
        'product',
        'robot',
        'rbtx_entity',
        'attachment',
    );
}

/**
 * @return list<string>
 */
function get_object_taxonomies(
    string $objectType,
    string $output = 'names'
): array {
    return $objectType === 'product'
        ? array(
            'product_cat',
            'product_tag',
            'product_brand',
            'pa_color',
            'product_shipping_class',
            'robot_application',
            'product_type',
            'product_visibility',
        )
        : array();
}

function get_taxonomy(string $taxonomy): object|false
{
    $restBases = array(
        'product_cat' => array('product_cat', 'product-category'),
        'product_tag' => array('product_tag', 'product-tag'),
        'product_brand' => array('brands', 'product-brand'),
        'pa_color' => array('pa_color', 'product-attribute/color'),
        'product_shipping_class' => array(
            'shipping_classes',
            'product-shipping-class',
        ),
        'robot_application' => array(
            'robot_applications',
            'robot-application',
        ),
        'product_type' => array('product_type', 'product-type'),
        'product_visibility' => array(
            'product_visibility',
            'product-visibility',
        ),
    );

    return array_key_exists($taxonomy, $restBases)
        ? (object) array(
            'rest_base' => $restBases[$taxonomy][0],
            'rewrite' => array('slug' => $restBases[$taxonomy][1]),
        )
        : false;
}

function home_url(string $path = ''): string
{
    return 'https://robbottx.com' . $path;
}

function status_header(int $statusCode): void
{
    $GLOBALS['rbtx_status_headers'][] = $statusCode;
}

function nocache_headers(): void
{
    ++$GLOBALS['rbtx_nocache_headers'];
}

function esc_html__(string $text, string $domain = 'default'): string
{
    return $text;
}

/**
 * @param array<string, mixed> $arguments
 */
function wp_die(
    string $message,
    string $title = '',
    array $arguments = array()
): void {
    $GLOBALS['rbtx_wp_die_calls'][] = array(
        'arguments' => $arguments,
        'message' => $message,
        'title' => $title,
    );
}

function is_singular(string|array $postType = ''): bool
{
    return ($GLOBALS['rbtx_request']['singular'] ?? null) === $postType;
}

function is_post_type_archive(string|array $postType = ''): bool
{
    return ($GLOBALS['rbtx_request']['post_type_archive'] ?? null) === $postType;
}

function is_page(string|array $page = ''): bool
{
    $slug = $GLOBALS['rbtx_request']['page'] ?? null;

    return is_array($page)
        ? in_array($slug, $page, true)
        : $slug === $page;
}

function is_single(string|array $post = ''): bool
{
    $slug = $GLOBALS['rbtx_request']['single'] ?? null;

    return is_array($post)
        ? in_array($slug, $post, true)
        : $slug === $post;
}

function is_tax(string|array $taxonomy = ''): bool
{
    $value = $GLOBALS['rbtx_request']['tax'] ?? null;

    return is_array($taxonomy)
        ? in_array($value, $taxonomy, true)
        : $value === $taxonomy;
}

function is_category(string|int|array $category = ''): bool
{
    return ($GLOBALS['rbtx_request']['category'] ?? null) === $category;
}

function is_author(): bool
{
    return (bool) ($GLOBALS['rbtx_request']['author'] ?? false);
}

function expect(bool $condition, string $message): void
{
    ++$GLOBALS['rbtx_assertions'];

    if ($condition) {
        return;
    }

    fwrite(STDERR, "FAIL: {$message}\n");
    exit(1);
}

function expectSame(mixed $expected, mixed $actual, string $message): void
{
    expect(
        $expected === $actual,
        $message
            . "\nExpected: "
            . var_export($expected, true)
            . "\nActual: "
            . var_export($actual, true)
    );
}

final class DiscoveryQuery
{
    private bool $is404 = false;

    /**
     * @param array<string, bool> $flags
     * @param array<string, mixed> $variables
     */
    public function __construct(
        private array $flags = array(),
        private array $variables = array()
    ) {
    }

    public function is_main_query(): bool
    {
        return $this->flags['main'] ?? true;
    }

    public function is_search(): bool
    {
        return $this->flags['search'] ?? false;
    }

    public function is_feed(): bool
    {
        return $this->flags['feed'] ?? false;
    }

    public function is_home(): bool
    {
        return $this->flags['home'] ?? false;
    }

    public function is_date(): bool
    {
        return $this->flags['date'] ?? false;
    }

    public function is_author(): bool
    {
        return $this->flags['author'] ?? false;
    }

    public function is_category(string $slug = ''): bool
    {
        return ($this->flags['category'] ?? false)
            && ($this->variables['category_name'] ?? '') === $slug;
    }

    public function is_post_type_archive(string $postType = ''): bool
    {
        return ($this->flags['post_type_archive'] ?? false)
            && ($this->variables['post_type'] ?? '') === $postType;
    }

    public function is_tax(string|array $taxonomy = ''): bool
    {
        if (! ($this->flags['tax'] ?? false)) {
            return false;
        }

        $current = (string) ($this->variables['taxonomy'] ?? '');

        return is_array($taxonomy)
            ? in_array($current, $taxonomy, true)
            : $current === $taxonomy;
    }

    public function get(string $key): mixed
    {
        return $this->variables[$key] ?? '';
    }

    public function set(string $key, mixed $value): void
    {
        $this->variables[$key] = $value;
    }

    public function set_404(): void
    {
        $this->is404 = true;
    }

    public function is404(): bool
    {
        return $this->is404;
    }

    /**
     * @return array<string, mixed>
     */
    public function variables(): array
    {
        return $this->variables;
    }
}

final class DiscoveryRequest
{
    public function __construct(
        private string $route,
        private string $method = 'GET'
    ) {
    }

    public function get_route(): string
    {
        return $this->route;
    }

    public function get_method(): string
    {
        return $this->method;
    }
}

require dirname(__DIR__, 2)
    . '/wp-content/plugins/robbottx-core/src/Discovery/PublicDiscovery.php';

use RobbottX\Core\Discovery\PublicDiscovery;

PublicDiscovery::boot();

$expectedHooks = array(
    'wp_sitemaps_post_types',
    'wp_sitemaps_posts_query_args',
    'wp_sitemaps_taxonomies_query_args',
    'wp_sitemaps_taxonomies',
    'wp_sitemaps_add_provider',
    'rank_math/sitemap/exclude_post_type',
    'rank_math/sitemap/exclude_taxonomy',
    'rank_math/sitemap/html_sitemap_post_types',
    'rank_math/sitemap/html_sitemap_taxonomies',
    'pre_get_posts',
    'wp_loaded',
    'template_redirect',
    'redirect_canonical',
    'old_slug_redirect_post_id',
    'old_slug_redirect_url',
    'wp_robots',
    'rank_math/frontend/robots',
    'rest_post_search_query',
    'rest_post_query',
    'rest_page_query',
    'rest_robot_query',
    'rest_product_query',
    'rest_product_cat_query',
    'rest_product_tag_query',
    'rest_product_brand_query',
    'init',
    'rest_term_search_query',
    'rest_category_query',
    'rest_user_query',
    'rest_pre_dispatch',
    'wp_list_pages_excludes',
    'widget_posts_args',
    'widget_categories_args',
    'widget_categories_dropdown_args',
    'wp_list_authors_args',
    'wp_get_nav_menu_items',
);

foreach ($expectedHooks as $hook) {
    expect(isset($GLOBALS['rbtx_hooks'][$hook]), "registered {$hook}");
}

PublicDiscovery::registerInactiveCommerceRestFilters();
expect(
    isset($GLOBALS['rbtx_hooks']['rest_pa_color_query']),
    'dynamic product attribute REST collection filter is registered'
);
expect(
    isset($GLOBALS['rbtx_hooks']['rest_product_type_query']),
    'every taxonomy attached to products receives the collection filter'
);
expect(
    isset($GLOBALS['rbtx_hooks']['rest_product_shipping_class_query']),
    'product shipping class REST collection filter is registered'
);
expect(
    isset($GLOBALS['rbtx_hooks']['rest_robot_application_query']),
    'custom product taxonomy REST collection filter is registered'
);

expectSame(
    2,
    $GLOBALS['rbtx_hooks']['wp_sitemaps_posts_query_args']['accepted_args'],
    'sitemap post query receives the post type'
);
expectSame(
    3,
    $GLOBALS['rbtx_hooks']['wp_get_nav_menu_items']['accepted_args'],
    'navigation filter accepts the full core signature'
);
expectSame(
    3,
    $GLOBALS['rbtx_hooks']['rest_pre_dispatch']['accepted_args'],
    'REST detail gate accepts the full core signature'
);
expectSame(
    0,
    $GLOBALS['rbtx_hooks']['template_redirect']['priority'],
    'retired route transition runs before canonical redirects'
);
expect(
    $GLOBALS['rbtx_hooks']['wp_loaded']['priority'] < 0,
    'classic commerce requests are blocked before WooCommerce handlers'
);
expectSame(
    PHP_INT_MAX,
    $GLOBALS['rbtx_hooks']['init']['priority'],
    'dynamic product taxonomy filters register after commerce taxonomies'
);
expectSame(
    2,
    $GLOBALS['rbtx_hooks']['redirect_canonical']['accepted_args'],
    'canonical redirect filter receives the requested URL'
);
foreach (
    array('old_slug_redirect_post_id', 'old_slug_redirect_url')
    as $oldSlugHook
) {
    expectSame(
        PHP_INT_MAX,
        $GLOBALS['rbtx_hooks'][$oldSlugHook]['priority'],
        'old-slug redirect guard runs at the final priority'
    );
    expectSame(
        1,
        $GLOBALS['rbtx_hooks'][$oldSlugHook]['accepted_args'],
        'old-slug redirect guard receives the core value'
    );
}

foreach (
    array(
        array('singular' => 'robot'),
        array('singular' => 'product'),
        array('post_type_archive' => 'robot'),
        array('post_type_archive' => 'product'),
        array('tax' => 'product_cat'),
        array('tax' => 'product_brand'),
        array('tax' => 'pa_color'),
        array('tax' => 'product_shipping_class'),
        array('tax' => 'robot_application'),
        array('page' => 'sample-page'),
        array('page' => 'robots-catalog'),
        array('page' => 'shop'),
        array('page' => 'cart'),
        array('page' => 'checkout'),
        array('page' => 'my-account'),
        array('single' => 'hello-world'),
        array('category' => 'uncategorized'),
        array('author' => true),
    ) as $request
) {
    $GLOBALS['rbtx_request'] = $request;
    $GLOBALS['rbtx_status_headers'] = array();
    $GLOBALS['rbtx_nocache_headers'] = 0;
    $GLOBALS['wp_query'] = new DiscoveryQuery();

    PublicDiscovery::retireFrontendRequest();

    expect(
        $GLOBALS['wp_query']->is404(),
        'retired public request uses the theme error template'
    );
    expectSame(
        true,
        $GLOBALS['wp_query']->get('_robbottx_retired_request'),
        'retired public request keeps its internal robots flag'
    );
    expectSame(
        array(410),
        $GLOBALS['rbtx_status_headers'],
        'retired public request returns HTTP 410'
    );
    expectSame(
        1,
        $GLOBALS['rbtx_nocache_headers'],
        'retired public request disables response caching'
    );

    $GLOBALS['rbtx_request'] = array();
    $robots = PublicDiscovery::filterRobots(array('index' => true));
    expectSame(
        true,
        $robots['noindex'],
        'retired request remains noindex after the 404 query transition'
    );
    expect(! isset($robots['index']), 'retired request removes index');
    expectSame(
        false,
        PublicDiscovery::filterCanonicalRedirect(
            'https://robbottx.com/other/',
            'https://robbottx.com/retired/'
        ),
        'retired public request cannot be canonically redirected'
    );
    expectSame(
        0,
        PublicDiscovery::filterOldSlugRedirectPostId(55),
        'retired public request cannot resolve an old-slug redirect post'
    );
    expectSame(
        false,
        PublicDiscovery::filterOldSlugRedirectUrl(
            'https://robbottx.com/current/'
        ),
        'retired public request cannot emit an old-slug redirect'
    );
}

$GLOBALS['rbtx_request'] = array('singular' => 'robot');
$GLOBALS['rbtx_status_headers'] = array();
$GLOBALS['rbtx_nocache_headers'] = 0;
$GLOBALS['rbtx_wp_die_calls'] = array();
$GLOBALS['wp_query'] = null;
PublicDiscovery::retireFrontendRequest();
expectSame(
    array(410),
    $GLOBALS['rbtx_status_headers'],
    'missing query state still returns HTTP 410'
);
expectSame(
    1,
    $GLOBALS['rbtx_nocache_headers'],
    'missing query state still disables response caching'
);
expectSame(
    1,
    count($GLOBALS['rbtx_wp_die_calls']),
    'missing query state uses the fail-closed WordPress error response'
);
expectSame(
    410,
    $GLOBALS['rbtx_wp_die_calls'][0]['arguments']['response'],
    'fail-closed WordPress error response keeps HTTP 410'
);

$GLOBALS['rbtx_status_headers'] = array();
$GLOBALS['rbtx_nocache_headers'] = 0;
$GLOBALS['rbtx_request'] = array('singular' => 'rbtx_entity');
$GLOBALS['wp_query'] = new DiscoveryQuery();
PublicDiscovery::retireFrontendRequest();
expect(
    ! $GLOBALS['wp_query']->is404(),
    'ordinary RobbottX entity route remains available'
);
expectSame(
    array(),
    $GLOBALS['rbtx_status_headers'],
    'ordinary RobbottX entity route keeps its status'
);
expectSame(
        'https://robbottx.com/ordinary/',
        PublicDiscovery::filterCanonicalRedirect(
            'https://robbottx.com/ordinary/',
            'https://robbottx.com/old-ordinary/'
        ),
    'ordinary canonical redirects remain available'
);
expectSame(
    55,
    PublicDiscovery::filterOldSlugRedirectPostId(55),
    'ordinary old-slug redirect post resolution remains available'
);
expectSame(
    'https://robbottx.com/current/',
    PublicDiscovery::filterOldSlugRedirectUrl(
        'https://robbottx.com/current/'
    ),
    'ordinary old-slug redirect URLs remain available'
);

$GLOBALS['rbtx_request'] = array('singular' => 'robot');
$GLOBALS['rbtx_admin'] = true;
$GLOBALS['wp_query'] = new DiscoveryQuery();
PublicDiscovery::retireFrontendRequest();
expect(! $GLOBALS['wp_query']->is404(), 'administrators keep retired access');
$GLOBALS['rbtx_admin'] = false;

$GLOBALS['rbtx_can_edit'] = true;
$GLOBALS['wp_query'] = new DiscoveryQuery();
PublicDiscovery::retireFrontendRequest();
expect(! $GLOBALS['wp_query']->is404(), 'editors keep retired access');
$GLOBALS['rbtx_can_edit'] = false;
$GLOBALS['rbtx_request'] = array();
$GLOBALS['wp_query'] = new DiscoveryQuery();

$postTypes = PublicDiscovery::filterSitemapPostTypes(
    array(
        'post' => (object) array(),
        'page' => (object) array(),
        'product' => (object) array(),
        'robot' => (object) array(),
    )
);
expect(! isset($postTypes['robot']), 'retired post type leaves the sitemap');
expect(
    ! isset($postTypes['product']),
    'inactive product post type leaves the sitemap'
);

$postSitemap = PublicDiscovery::filterSitemapPostQueryArgs(
    array('post__not_in' => array(900)),
    'post'
);
expectSame(
    array(900, 101),
    $postSitemap['post__not_in'],
    'default post is excluded from the post sitemap'
);

$pageSitemap = PublicDiscovery::filterSitemapPostQueryArgs(array(), 'page');
expectSame(
    array(201, 202, 29, 30, 31, 32),
    $pageSitemap['post__not_in'],
    'default, retired, and inactive commerce pages leave the page sitemap'
);

$robotSitemap = PublicDiscovery::filterSitemapPostQueryArgs(array(), 'robot');
expectSame(
    array(0),
    $robotSitemap['post__in'],
    'retired post type sitemap cannot return records'
);

$productSitemap = PublicDiscovery::filterSitemapPostQueryArgs(
    array('post_type' => 'product'),
    'product'
);
expectSame(
    array('post_type' => 'product', 'post__in' => array(0)),
    $productSitemap,
    'inactive product sitemap cannot return records'
);

$categorySitemap = PublicDiscovery::filterSitemapTaxonomyQueryArgs(
    array('exclude' => '900'),
    'category'
);
expectSame(
    array(900, 301),
    $categorySitemap['exclude'],
    'default category is excluded while existing exclusions remain'
);
expectSame(
    array('hide_empty' => true, 'include' => array(0)),
    PublicDiscovery::filterSitemapTaxonomyQueryArgs(
        array('hide_empty' => true),
        'product_cat'
    ),
    'inactive product taxonomy sitemap cannot return terms'
);
foreach (
    array(
        'product_brand',
        'pa_color',
        'product_shipping_class',
        'robot_application',
    ) as $taxonomy
) {
    expectSame(
        array(0),
        PublicDiscovery::filterSitemapTaxonomyQueryArgs(
            array(),
            $taxonomy
        )['include'],
        "{$taxonomy} sitemap cannot return inactive commerce terms"
    );
}

$sitemapTaxonomies = PublicDiscovery::filterSitemapTaxonomies(
    array(
        'category' => (object) array(),
        'post_tag' => (object) array(),
        'product_cat' => (object) array(),
        'product_tag' => (object) array(),
        'product_brand' => (object) array(),
        'pa_color' => (object) array(),
        'product_shipping_class' => (object) array(),
        'robot_application' => (object) array(),
        'product_type' => (object) array(),
        'product_visibility' => (object) array(),
    )
);
expect(
    isset($sitemapTaxonomies['category']),
    'ordinary categories remain in taxonomy sitemaps'
);
expect(
    isset($sitemapTaxonomies['post_tag']),
    'ordinary tags remain in taxonomy sitemaps'
);
expect(
    ! isset($sitemapTaxonomies['product_cat']),
    'inactive product categories leave taxonomy sitemaps'
);
expect(
    ! isset($sitemapTaxonomies['product_tag']),
    'inactive product tags leave taxonomy sitemaps'
);
expect(
    ! isset($sitemapTaxonomies['product_brand']),
    'inactive product brands leave taxonomy sitemaps'
);
expect(
    ! isset($sitemapTaxonomies['pa_color']),
    'inactive product attributes leave taxonomy sitemaps'
);
expect(
    ! isset($sitemapTaxonomies['product_shipping_class']),
    'inactive product shipping classes leave taxonomy sitemaps'
);
expect(
    ! isset($sitemapTaxonomies['robot_application']),
    'custom product taxonomies leave taxonomy sitemaps'
);
expect(
    ! isset($sitemapTaxonomies['product_type']),
    'every product taxonomy leaves taxonomy sitemaps'
);
expect(
    ! isset($sitemapTaxonomies['product_visibility']),
    'product visibility terms leave taxonomy sitemaps'
);
foreach (array('robot', 'product') as $postType) {
    expect(
        PublicDiscovery::filterRankMathSitemapPostType(false, $postType),
        "Rank Math excludes {$postType} records"
    );
}
expect(
    ! PublicDiscovery::filterRankMathSitemapPostType(false, 'post'),
    'Rank Math keeps ordinary posts'
);
expect(
    PublicDiscovery::filterRankMathSitemapPostType(true, 'post'),
    'Rank Math preserves an existing post type exclusion'
);
foreach (
    array(
        'product_cat',
        'product_tag',
        'product_brand',
        'pa_color',
        'product_shipping_class',
        'robot_application',
    ) as $taxonomy
) {
    expect(
        PublicDiscovery::filterRankMathSitemapTaxonomy(false, $taxonomy),
        "Rank Math excludes {$taxonomy}"
    );
}
expect(
    ! PublicDiscovery::filterRankMathSitemapTaxonomy(false, 'category'),
    'Rank Math keeps ordinary categories'
);
expect(
    PublicDiscovery::filterRankMathSitemapTaxonomy(true, 'category'),
    'Rank Math preserves an existing taxonomy exclusion'
);
expectSame(
    array('post', 'page'),
    PublicDiscovery::filterRankMathHtmlSitemapPostTypes(
        array('post', 'product', 'robot', 'page')
    ),
    'Rank Math HTML sitemap excludes inactive and retired records'
);
expectSame(
    array('post', 'page'),
    array_keys(
        PublicDiscovery::filterRankMathHtmlSitemapPostTypes(
            array(
                'post' => (object) array('name' => 'post'),
                'product' => (object) array('name' => 'product'),
                'page' => (object) array('name' => 'page'),
            )
        )
    ),
    'Rank Math HTML sitemap preserves associative post type settings'
);
expectSame(
    array('category', 'post_tag'),
    PublicDiscovery::filterRankMathHtmlSitemapTaxonomies(
        array(
            'category',
            'product_cat',
            'product_brand',
            'pa_color',
            'product_shipping_class',
            'robot_application',
            'post_tag',
        )
    ),
    'Rank Math HTML sitemap excludes inactive commerce taxonomies'
);
expectSame(
    array('category'),
    array_keys(
        PublicDiscovery::filterRankMathHtmlSitemapTaxonomies(
            array(
                'category' => (object) array('name' => 'category'),
                'product_tag' => (object) array('name' => 'product_tag'),
            )
        )
    ),
    'Rank Math HTML sitemap preserves associative taxonomy settings'
);

$provider = (object) array('name' => 'posts');
expectSame(
    false,
    PublicDiscovery::filterSitemapProvider($provider, 'users'),
    'author sitemap provider is disabled'
);
expectSame(
    $provider,
    PublicDiscovery::filterSitemapProvider($provider, 'posts'),
    'other sitemap providers remain available'
);

$search = new DiscoveryQuery(
    array('search' => true),
    array('post_type' => 'any')
);
PublicDiscovery::filterMainQuery($search);
$searchVariables = $search->variables();
expect(
    ! in_array('robot', $searchVariables['post_type'], true),
    'public search excludes the retired post type'
);
expect(
    ! in_array('product', $searchVariables['post_type'], true),
    'public search excludes inactive products'
);
expect(
    in_array('attachment', $searchVariables['post_type'], true),
    'public search does not hide media outside the policy scope'
);
expectSame(
    array(101, 201, 202, 29, 30, 31, 32),
    $searchVariables['post__not_in'],
    'public search excludes default and inactive commerce content'
);

$productSearch = new DiscoveryQuery(
    array('search' => true),
    array('post_type' => 'product')
);
PublicDiscovery::filterMainQuery($productSearch);
expectSame(
    array(0),
    $productSearch->variables()['post__in'],
    'inactive product search returns no results'
);

$robotSearch = new DiscoveryQuery(
    array('search' => true),
    array('post_type' => 'robot')
);
PublicDiscovery::filterMainQuery($robotSearch);
expectSame(
    array(0),
    $robotSearch->variables()['post__in'],
    'retired post type search returns no results'
);

$includedSearch = new DiscoveryQuery(
    array('search' => true),
    array(
        'post_type' => 'post',
        'post__in' => array(101, 500),
    )
);
PublicDiscovery::filterMainQuery($includedSearch);
expectSame(
    array(500),
    $includedSearch->variables()['post__in'],
    'explicit public search includes cannot restore excluded content'
);

$feed = new DiscoveryQuery(
    array('feed' => true),
    array('post_type' => 'any')
);
PublicDiscovery::filterMainQuery($feed);
expect(
    ! in_array('robot', $feed->variables()['post_type'], true),
    'public feed excludes the retired post type'
);
expectSame(
    array(101, 201, 202, 29, 30, 31, 32),
    $feed->variables()['post__not_in'],
    'public feed excludes default and inactive commerce content'
);

foreach (
    array(
        'author' => new DiscoveryQuery(array('author' => true)),
        'category' => new DiscoveryQuery(
            array('category' => true),
            array('category_name' => 'uncategorized')
        ),
        'robot_archive' => new DiscoveryQuery(
            array('post_type_archive' => true),
            array('post_type' => 'robot')
        ),
        'product_archive' => new DiscoveryQuery(
            array('post_type_archive' => true),
            array('post_type' => 'product')
        ),
        'product_brand_archive' => new DiscoveryQuery(
            array('tax' => true),
            array('taxonomy' => 'product_brand')
        ),
        'product_attribute_archive' => new DiscoveryQuery(
            array('tax' => true),
            array('taxonomy' => 'pa_color')
        ),
        'product_shipping_archive' => new DiscoveryQuery(
            array('tax' => true),
            array('taxonomy' => 'product_shipping_class')
        ),
        'custom_product_taxonomy_archive' => new DiscoveryQuery(
            array('tax' => true),
            array('taxonomy' => 'robot_application')
        ),
    ) as $label => $query
) {
    PublicDiscovery::filterMainQuery($query);
    expectSame(
        array(0),
        $query->variables()['post__in'],
        "{$label} public archive returns no results"
    );
}

foreach (array('home', 'date') as $flag) {
    $query = new DiscoveryQuery(array($flag => true));
    PublicDiscovery::filterMainQuery($query);
    expectSame(
        array(101, 201, 202, 29, 30, 31, 32),
        $query->variables()['post__not_in'],
        "{$flag} discovery excludes default and inactive commerce content"
    );
}

$accountQuery = new DiscoveryQuery(
    array(),
    array('pagename' => 'my-account')
);
PublicDiscovery::filterMainQuery($accountQuery);
expectSame(
    array('pagename' => 'my-account'),
    $accountQuery->variables(),
    'account page query stays unchanged'
);

$GLOBALS['rbtx_admin'] = true;
$adminQuery = new DiscoveryQuery(
    array('search' => true),
    array('post_type' => 'robot')
);
PublicDiscovery::filterMainQuery($adminQuery);
expectSame(
    array('post_type' => 'robot'),
    $adminQuery->variables(),
    'administrative search remains available'
);
$GLOBALS['rbtx_admin'] = false;

foreach (
    array(
        array('singular' => 'robot'),
        array('singular' => 'product'),
        array('post_type_archive' => 'robot'),
        array('post_type_archive' => 'product'),
        array('tax' => 'product_tag'),
        array('tax' => 'product_brand'),
        array('tax' => 'pa_color'),
        array('tax' => 'product_shipping_class'),
        array('tax' => 'robot_application'),
        array('page' => 'sample-page'),
        array('page' => 'robots-catalog'),
        array('page' => 'shop'),
        array('page' => 'cart'),
        array('page' => 'checkout'),
        array('page' => 'my-account'),
        array('single' => 'hello-world'),
        array('category' => 'uncategorized'),
        array('author' => true),
    ) as $request
) {
    $GLOBALS['rbtx_request'] = $request;
    $robots = PublicDiscovery::filterRobots(
        array('index' => true, 'nofollow' => true)
    );
    expectSame(true, $robots['noindex'], 'excluded request is noindex');
    expectSame(true, $robots['follow'], 'excluded request permits link following');
    expect(! isset($robots['index']), 'conflicting index directive is removed');
    expect(! isset($robots['nofollow']), 'conflicting nofollow directive is removed');

    $rankMathRobots = PublicDiscovery::filterRankMathRobots(
        array('index' => 'index', 'nofollow' => 'nofollow')
    );
    expectSame(
        'noindex',
        $rankMathRobots['noindex'],
        'Rank Math receives the matching noindex directive'
    );
    expectSame(
        'follow',
        $rankMathRobots['follow'],
        'Rank Math receives the matching follow directive'
    );
    expect(
        ! isset($rankMathRobots['index']),
        'Rank Math conflicting index directive is removed'
    );
    expect(
        ! isset($rankMathRobots['nofollow']),
        'Rank Math conflicting nofollow directive is removed'
    );
}

$GLOBALS['rbtx_request'] = array('singular' => 'rbtx_entity');
expectSame(
    array('max-image-preview' => 'large'),
    PublicDiscovery::filterRobots(array('max-image-preview' => 'large')),
    'ordinary entity robots directives stay unchanged'
);
expectSame(
    array('index' => 'index'),
    PublicDiscovery::filterRankMathRobots(array('index' => 'index')),
    'ordinary entity Rank Math directives stay unchanged'
);
$GLOBALS['rbtx_request'] = array();

$restSearch = PublicDiscovery::filterRestPostSearchQuery(
    array('post_type' => array('post', 'product', 'robot')),
    null
);
expectSame(
    array('post'),
    $restSearch['post_type'],
    'public machine search excludes retired and inactive product records'
);
expectSame(
    array(101, 201, 202, 29, 30, 31, 32),
    $restSearch['post__not_in'],
    'public machine search excludes default and inactive commerce content'
);
$defaultRestSearch = PublicDiscovery::filterRestPostSearchQuery(array(), null);
expect(
    in_array('attachment', $defaultRestSearch['post_type'], true),
    'public machine search does not hide media outside the policy scope'
);

foreach (
    array(
        '/wp/v2/robot/77',
        '/wp/v2/robot/77/',
        '/wp/v2/product/55',
        '/wp/v2/product_cat/56',
        '/wp/v2/product_tag/57',
        '/wp/v2/brands/58',
        '/wp/v2/pa_color/59',
        '/wp/v2/shipping_classes/60',
        '/wp/v2/robot_applications/61',
        '/wp/v2/posts/101',
        '/wp/v2/pages/201',
        '/wp/v2/pages/202',
        '/wp/v2/pages/29',
        '/wp/v2/pages/30',
        '/wp/v2/pages/31',
        '/wp/v2/pages/32',
        '/wp/v2/categories/301',
        '/wp/v2/users/1',
    ) as $route
) {
    $detail = PublicDiscovery::filterRestDetailResponse(
        'continue',
        null,
        new DiscoveryRequest($route)
    );
    expect(
        $detail instanceof WP_Error,
        "{$route} public detail is hidden"
    );
    expectSame(
        404,
        $detail->data['status'] ?? null,
        "{$route} public detail returns 404"
    );
}

foreach (
    array(
        '/wp/v2/posts/500',
        '/wp/v2/pages/700',
        '/wp/v2/categories/500',
        '/wp/v2/users/me',
        '/wp/v2/products/55',
    ) as $route
) {
    expectSame(
        'continue',
        PublicDiscovery::filterRestDetailResponse(
            'continue',
            null,
            new DiscoveryRequest($route)
        ),
        "{$route} remains outside the detail policy"
    );
}

expect(
    PublicDiscovery::filterRestDetailResponse(
        'continue',
        null,
        new DiscoveryRequest('/wp/v2/robot/77', 'HEAD')
    ) instanceof WP_Error,
    'retired record HEAD detail is hidden'
);
expect(
    PublicDiscovery::filterRestDetailResponse(
        'continue',
        null,
        new DiscoveryRequest('/wp/v2/product/55', 'HEAD')
    ) instanceof WP_Error,
    'inactive product HEAD detail is hidden'
);
expect(
    PublicDiscovery::filterRestDetailResponse(
        'continue',
        null,
        new DiscoveryRequest('/wc/store/v1/products', 'GET')
    ) instanceof WP_Error,
    'inactive Store API product collection is hidden'
);
expect(
    PublicDiscovery::filterRestDetailResponse(
        'continue',
        null,
        new DiscoveryRequest('/wc/store/v1/cart', 'POST')
    ) instanceof WP_Error,
    'inactive Store API write surface is hidden'
);
expectSame(
    'continue',
    PublicDiscovery::filterRestDetailResponse(
        'continue',
        null,
        new DiscoveryRequest('/wp/v2/robot/77', 'POST')
    ),
    'write requests continue to WordPress capability checks'
);

foreach (
    array(
        array('/wp/v2/robot/77', 'edit_post:77', 'list_users'),
        array('/wp/v2/product/55', 'edit_post:55', 'list_users'),
        array('/wp/v2/posts/101', 'edit_post:101', 'manage_categories'),
        array('/wp/v2/pages/201', 'edit_post:201', 'list_users'),
        array('/wp/v2/pages/202', 'edit_post:202', 'manage_categories'),
        array('/wp/v2/pages/29', 'edit_post:29', 'list_users'),
        array('/wp/v2/pages/30', 'edit_post:30', 'manage_categories'),
        array('/wp/v2/pages/31', 'edit_post:31', 'list_users'),
        array('/wp/v2/pages/32', 'edit_post:32', 'manage_categories'),
        array('/wp/v2/categories/301', 'manage_categories', 'list_users'),
        array('/wp/v2/users/1', 'list_users', 'manage_categories'),
    ) as [$route, $requiredCapability, $unrelatedCapability]
) {
    $GLOBALS['rbtx_caps'] = array($requiredCapability);
    expectSame(
        'continue',
        PublicDiscovery::filterRestDetailResponse(
            'continue',
            null,
            new DiscoveryRequest($route)
        ),
        "{$route} preserves resource-specific editorial access"
    );

    $GLOBALS['rbtx_caps'] = array($unrelatedCapability);
    expect(
        PublicDiscovery::filterRestDetailResponse(
            'continue',
            null,
            new DiscoveryRequest($route)
        ) instanceof WP_Error,
        "{$route} rejects an unrelated editorial capability"
    );
}
$GLOBALS['rbtx_caps'] = array();

$GLOBALS['rbtx_can_edit'] = true;
foreach (
    array(
        '/wp/v2/product_cat/56',
        '/wp/v2/product_tag/57',
        '/wp/v2/brands/58',
        '/wp/v2/pa_color/59',
        '/wp/v2/shipping_classes/60',
        '/wp/v2/robot_applications/61',
    ) as $route
) {
    expectSame(
        'continue',
        PublicDiscovery::filterRestDetailResponse(
            'continue',
            null,
            new DiscoveryRequest($route)
        ),
        "{$route} preserves editorial taxonomy detail access"
    );
}
$GLOBALS['rbtx_can_edit'] = false;

$restRobot = PublicDiscovery::filterRestRobotQuery(array(), null);
expectSame(
    array(0),
    $restRobot['post__in'],
    'public retired record collection returns no results'
);
$restProduct = PublicDiscovery::filterRestProductQuery(array(), null);
expectSame(
    array(0),
    $restProduct['post__in'],
    'public inactive product collection returns no results'
);
expectSame(
    array(0),
    PublicDiscovery::filterRestProductTaxonomyQuery(
        array(),
        null
    )['include'],
    'public inactive product taxonomy collection returns no results'
);
foreach (
    array(
        'rest_product_brand_query',
        'rest_pa_color_query',
        'rest_product_shipping_class_query',
        'rest_robot_application_query',
    ) as $hook
) {
    $callback = $GLOBALS['rbtx_hooks'][$hook]['callback'];
    expectSame(
        array(0),
        $callback(array(), null)['include'],
        "{$hook} hides its public collection"
    );
}
expectSame(
    array(101),
    PublicDiscovery::filterRestPostQuery(array(), null)['post__not_in'],
    'public post collection excludes the default post'
);
expectSame(
    array(201, 202, 29, 30, 31, 32),
    PublicDiscovery::filterRestPageQuery(array(), null)['post__not_in'],
    'public page collection excludes default and inactive commerce pages'
);
expectSame(
    array(500),
    PublicDiscovery::filterRestPostQuery(
        array('post__in' => array(101, 500)),
        null
    )['post__in'],
    'public post includes remove the excluded default post'
);
expectSame(
    array(0),
    PublicDiscovery::filterRestPageQuery(
        array('post__in' => array(201, 202, 29, 30, 31, 32)),
        null
    )['post__in'],
    'public page includes cannot select only excluded pages'
);
expectSame(
    array(301),
    PublicDiscovery::filterRestTermSearchQuery(array(), null)['exclude'],
    'public term search excludes the default category'
);
expectSame(
    array(301),
    PublicDiscovery::filterRestCategoryQuery(array(), null)['exclude'],
    'public category collection excludes the default category'
);
expectSame(
    array(500),
    PublicDiscovery::filterRestCategoryQuery(
        array('include' => array(301, 500)),
        null
    )['include'],
    'public category includes remove the excluded default category'
);
expectSame(
    array(0),
    PublicDiscovery::filterRestTermSearchQuery(
        array('include' => array(301)),
        null
    )['include'],
    'public term includes cannot select only the excluded category'
);
expectSame(
    array(0),
    PublicDiscovery::filterRestUserQuery(array(), null)['include'],
    'public user collection does not advertise author archives'
);

$GLOBALS['rbtx_can_edit'] = true;
$editorRest = array('post_type' => array('robot'));
expectSame(
    $editorRest,
    PublicDiscovery::filterRestPostSearchQuery($editorRest, null),
    'authenticated editorial machine search remains available'
);
expectSame(
    array('orderby' => 'title'),
    PublicDiscovery::filterRestProductQuery(
        array('orderby' => 'title'),
        null
    ),
    'authenticated editorial product collection remains available'
);
expectSame(
    array('orderby' => 'name'),
    PublicDiscovery::filterRestProductTaxonomyQuery(
        array('orderby' => 'name'),
        null
    ),
    'authenticated editorial product taxonomy remains available'
);
expectSame(
    'continue',
    PublicDiscovery::filterRestDetailResponse(
        'continue',
        null,
        new DiscoveryRequest('/wc/store/v1/products')
    ),
    'authenticated editorial Store API remains available'
);
expectSame(
    array('orderby' => 'name'),
    PublicDiscovery::filterRestCategoryQuery(
        array('orderby' => 'name'),
        null
    ),
    'authenticated editorial category collection remains available'
);
expectSame(
    array('roles' => array('author')),
    PublicDiscovery::filterRestUserQuery(
        array('roles' => array('author')),
        null
    ),
    'authenticated editorial user collection remains available'
);
$editorSearch = new DiscoveryQuery(
    array('search' => true),
    array('post_type' => 'robot')
);
PublicDiscovery::filterMainQuery($editorSearch);
expectSame(
    array('post_type' => 'robot'),
    $editorSearch->variables(),
    'authenticated editorial frontend search remains available'
);
expectSame(
    array(999),
    PublicDiscovery::filterPageListExcludes(array(999)),
    'authenticated editorial page lists remain complete'
);
$GLOBALS['rbtx_can_edit'] = false;

foreach (
    array(
        array(
            'get' => array('wc-ajax' => 'add_to_cart'),
            'post' => array(),
            'label' => 'WooCommerce AJAX request',
        ),
        array(
            'get' => array(),
            'post' => array('wc-ajax' => 'checkout'),
            'label' => 'posted WooCommerce AJAX request',
        ),
        array(
            'get' => array('add-to-cart' => '55'),
            'post' => array(),
            'label' => 'classic add to cart request',
        ),
    ) as $classicRequest
) {
    $_GET = $classicRequest['get'];
    $_POST = $classicRequest['post'];
    $_REQUEST = array_merge($_GET, $_POST);
    $GLOBALS['rbtx_status_headers'] = array();
    $GLOBALS['rbtx_nocache_headers'] = 0;
    $GLOBALS['rbtx_wp_die_calls'] = array();

    PublicDiscovery::blockClassicCommerceRequest();

    expectSame(
        array(404),
        $GLOBALS['rbtx_status_headers'],
        "{$classicRequest['label']} returns HTTP 404"
    );
    expectSame(
        1,
        $GLOBALS['rbtx_nocache_headers'],
        "{$classicRequest['label']} disables response caching"
    );
    expectSame(
        1,
        count($GLOBALS['rbtx_wp_die_calls']),
        "{$classicRequest['label']} stops before the commerce handler"
    );
    expectSame(
        404,
        $GLOBALS['rbtx_wp_die_calls'][0]['arguments']['response'] ?? null,
        "{$classicRequest['label']} keeps its HTTP status"
    );
    expectSame(
        'Not found.',
        $GLOBALS['rbtx_wp_die_calls'][0]['message'] ?? null,
        "{$classicRequest['label']} uses the generic public error"
    );
}

$_GET = array('s' => 'servo');
$_POST = array();
$_REQUEST = $_GET;
$GLOBALS['rbtx_status_headers'] = array();
$GLOBALS['rbtx_nocache_headers'] = 0;
$GLOBALS['rbtx_wp_die_calls'] = array();
PublicDiscovery::blockClassicCommerceRequest();
expectSame(
    array(),
    $GLOBALS['rbtx_status_headers'],
    'ordinary requests remain available'
);
expectSame(
    array(),
    $GLOBALS['rbtx_wp_die_calls'],
    'ordinary requests continue without a commerce error'
);

$_GET = array('wc-ajax' => 'add_to_cart');
$_POST = array();
$_REQUEST = $_GET;
$GLOBALS['rbtx_can_edit'] = true;
PublicDiscovery::blockClassicCommerceRequest();
expectSame(
    array(),
    $GLOBALS['rbtx_status_headers'],
    'editors retain classic commerce access'
);
$GLOBALS['rbtx_can_edit'] = false;
$GLOBALS['rbtx_admin'] = true;
PublicDiscovery::blockClassicCommerceRequest();
expectSame(
    array(),
    $GLOBALS['rbtx_status_headers'],
    'administrators retain classic commerce access'
);
$GLOBALS['rbtx_admin'] = false;
$_GET = array();
$_POST = array();
$_REQUEST = array();

expectSame(
    array(999, 201, 202, 29, 30, 31, 32),
    PublicDiscovery::filterPageListExcludes(array(999)),
    'automatic page lists exclude default and inactive commerce pages'
);
expectSame(
    array(900, 101),
    PublicDiscovery::filterRecentPostsArguments(
        array('post__not_in' => array(900))
    )['post__not_in'],
    'recent posts exclude the default post'
);
expectSame(
    array(900, 301),
    PublicDiscovery::filterCategoryListArguments(
        array('exclude' => '900')
    )['exclude'],
    'category lists exclude the default category'
);
expectSame(
    array(0),
    PublicDiscovery::filterAuthorListArguments(array())['include'],
    'automatic author lists return no public author links'
);

$navigation = array(
    (object) array(
        'title' => 'Shop',
        'type' => 'post_type',
        'object' => 'page',
        'object_id' => 700,
        'url' => 'https://robbottx.com/shop/',
    ),
    (object) array(
        'title' => 'Account',
        'type' => 'post_type',
        'object' => 'page',
        'object_id' => 701,
        'url' => 'https://robbottx.com/my-account/',
    ),
    (object) array(
        'title' => 'Product',
        'type' => 'post_type',
        'object' => 'product',
        'object_id' => 55,
        'url' => 'https://robbottx.com/product/example/',
    ),
    (object) array(
        'title' => 'Product category',
        'type' => 'taxonomy',
        'object' => 'product_cat',
        'object_id' => 56,
        'url' => 'https://robbottx.com/product-category/example/',
    ),
    (object) array(
        'title' => 'Product brand',
        'type' => 'taxonomy',
        'object' => 'product_brand',
        'object_id' => 57,
        'url' => 'https://robbottx.com/product-brand/example/',
    ),
    (object) array(
        'title' => 'Product color',
        'type' => 'taxonomy',
        'object' => 'pa_color',
        'object_id' => 58,
        'url' => 'https://robbottx.com/product-attribute/color/example/',
    ),
    (object) array(
        'title' => 'Product shipping class',
        'type' => 'taxonomy',
        'object' => 'product_shipping_class',
        'object_id' => 59,
        'url' => 'https://robbottx.com/product-shipping-class/example/',
    ),
    (object) array(
        'title' => 'Product application',
        'type' => 'taxonomy',
        'object' => 'robot_application',
        'object_id' => 60,
        'url' => 'https://robbottx.com/robot-application/example/',
    ),
    (object) array(
        'title' => 'Custom product brand',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/product-brand/example/',
    ),
    (object) array(
        'title' => 'Custom product color',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/product-attribute/color/example/',
    ),
    (object) array(
        'title' => 'Custom product shipping class',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/product-shipping-class/example/',
    ),
    (object) array(
        'title' => 'Custom product application',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/robot-application/example/',
    ),
    (object) array(
        'title' => 'Account orders',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/my-account/orders/',
    ),
    (object) array(
        'title' => 'Checkout payment',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/checkout/order-pay/123/',
    ),
    (object) array(
        'title' => 'Shop page',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/shop/page/2/',
    ),
    (object) array(
        'title' => 'Nested product',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/product/family/model/',
    ),
    (object) array(
        'title' => 'Nested retired record',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/robot/family/revision/',
    ),
    (object) array(
        'title' => 'Workshop',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/workshop/',
    ),
    (object) array(
        'title' => 'External shop page',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://example.com/shop/page/2/',
    ),
    (object) array(
        'title' => 'Catalog',
        'type' => 'post_type',
        'object' => 'page',
        'object_id' => 202,
        'url' => 'https://robbottx.com/robots-catalog/',
    ),
    (object) array(
        'title' => 'Retired records',
        'type' => 'post_type_archive',
        'object' => 'robot',
        'object_id' => 0,
        'url' => 'https://robbottx.com/robot/',
    ),
    (object) array(
        'title' => 'Default category',
        'type' => 'taxonomy',
        'object' => 'category',
        'object_id' => 301,
        'url' => 'https://robbottx.com/category/uncategorized/',
    ),
    (object) array(
        'title' => 'Author',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/author/editor/',
    ),
    (object) array(
        'title' => 'Retired custom record',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/robot/example-model/',
    ),
    (object) array(
        'title' => 'Retired custom archive',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://robbottx.com/robots/',
    ),
    (object) array(
        'title' => 'External author',
        'type' => 'custom',
        'object' => 'custom',
        'object_id' => 0,
        'url' => 'https://example.com/author/editor/',
    ),
);

$filteredNavigation = PublicDiscovery::filterNavigationItems($navigation);
expectSame(
    array('Workshop', 'External shop page', 'External author'),
    array_map(
        static fn (object $item): string => $item->title,
        $filteredNavigation
    ),
    'public navigation removes inactive commerce and keeps external links'
);

$GLOBALS['rbtx_admin'] = true;
expectSame(
    $navigation,
    PublicDiscovery::filterNavigationItems($navigation),
    'administrative navigation editing remains complete'
);
expectSame(
    array(999),
    PublicDiscovery::filterPageListExcludes(array(999)),
    'administrative page lists remain complete'
);
$GLOBALS['rbtx_admin'] = false;

expectSame(
    7,
    $GLOBALS['rbtx_post_lookups'],
    'exact content IDs are resolved once per request'
);
expectSame(
    1,
    $GLOBALS['rbtx_term_lookups'],
    'exact category ID is resolved once per request'
);

echo json_encode(
    array(
        'status' => 'PASS',
        'assertions' => $GLOBALS['rbtx_assertions'],
    ),
    JSON_THROW_ON_ERROR
);
