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

function home_url(string $path = ''): string
{
    return 'https://robbottx.com' . $path;
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

    public function get(string $key): mixed
    {
        return $this->variables[$key] ?? '';
    }

    public function set(string $key, mixed $value): void
    {
        $this->variables[$key] = $value;
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
    'wp_sitemaps_add_provider',
    'pre_get_posts',
    'wp_robots',
    'rank_math/frontend/robots',
    'rest_post_search_query',
    'rest_post_query',
    'rest_page_query',
    'rest_robot_query',
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

$postTypes = PublicDiscovery::filterSitemapPostTypes(
    array(
        'post' => (object) array(),
        'page' => (object) array(),
        'product' => (object) array(),
        'robot' => (object) array(),
    )
);
expect(! isset($postTypes['robot']), 'retired post type leaves the sitemap');
expect(isset($postTypes['product']), 'product sitemap remains available');

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
    array(201, 202),
    $pageSitemap['post__not_in'],
    'default and retired catalog pages are excluded from the page sitemap'
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
    array('post_type' => 'product'),
    $productSitemap,
    'product sitemap query stays unchanged'
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
    array('hide_empty' => true),
    PublicDiscovery::filterSitemapTaxonomyQueryArgs(
        array('hide_empty' => true),
        'product_cat'
    ),
    'product taxonomies stay unchanged'
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
    in_array('product', $searchVariables['post_type'], true),
    'public search preserves products'
);
expect(
    in_array('attachment', $searchVariables['post_type'], true),
    'public search does not hide media outside the policy scope'
);
expectSame(
    array(101, 201, 202),
    $searchVariables['post__not_in'],
    'public search excludes known default content'
);

$productSearch = new DiscoveryQuery(
    array('search' => true),
    array('post_type' => 'product')
);
PublicDiscovery::filterMainQuery($productSearch);
expectSame(
    'product',
    $productSearch->variables()['post_type'],
    'product search keeps its post type'
);
expect(
    ! isset($productSearch->variables()['post__in']),
    'product search is not forced empty'
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
    array(101, 201, 202),
    $feed->variables()['post__not_in'],
    'public feed excludes known default content'
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
        array(101, 201, 202),
        $query->variables()['post__not_in'],
        "{$flag} discovery excludes known default content"
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
        array('post_type_archive' => 'robot'),
        array('page' => 'sample-page'),
        array('page' => 'robots-catalog'),
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

$GLOBALS['rbtx_request'] = array('singular' => 'product');
expectSame(
    array('max-image-preview' => 'large'),
    PublicDiscovery::filterRobots(array('max-image-preview' => 'large')),
    'product robots directives stay unchanged'
);
expectSame(
    array('index' => 'index'),
    PublicDiscovery::filterRankMathRobots(array('index' => 'index')),
    'product Rank Math directives stay unchanged'
);
$GLOBALS['rbtx_request'] = array();

$restSearch = PublicDiscovery::filterRestPostSearchQuery(
    array('post_type' => array('post', 'product', 'robot')),
    null
);
expectSame(
    array('post', 'product'),
    $restSearch['post_type'],
    'public machine search preserves products and excludes retired records'
);
expectSame(
    array(101, 201, 202),
    $restSearch['post__not_in'],
    'public machine search excludes default content'
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
        '/wp/v2/posts/101',
        '/wp/v2/pages/201',
        '/wp/v2/pages/202',
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
        array('/wp/v2/posts/101', 'edit_post:101', 'manage_categories'),
        array('/wp/v2/pages/201', 'edit_post:201', 'list_users'),
        array('/wp/v2/pages/202', 'edit_post:202', 'manage_categories'),
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

$restRobot = PublicDiscovery::filterRestRobotQuery(array(), null);
expectSame(
    array(0),
    $restRobot['post__in'],
    'public retired record collection returns no results'
);
expectSame(
    array(101),
    PublicDiscovery::filterRestPostQuery(array(), null)['post__not_in'],
    'public post collection excludes the default post'
);
expectSame(
    array(201, 202),
    PublicDiscovery::filterRestPageQuery(array(), null)['post__not_in'],
    'public page collection excludes default pages'
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
        array('post__in' => array(201, 202)),
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

expectSame(
    array(999, 201, 202),
    PublicDiscovery::filterPageListExcludes(array(999)),
    'automatic page lists exclude default pages'
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
    array('Shop', 'Account', 'External author'),
    array_map(
        static fn (object $item): string => $item->title,
        $filteredNavigation
    ),
    'public navigation keeps commerce and external links only'
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
    3,
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
