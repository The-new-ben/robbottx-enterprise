# WordPress public discovery hook receipt

Retrieved: 2026-07-24
Authority: WordPress Developer Resources

## Scope

This receipt verifies the core hook contracts used by the RobbottX
non-destructive public discovery policy. It does not prove production behavior.
That requires a live URL, search, feed, sitemap, and robots audit after deploy.

## Verified contracts

### Main public queries

Source:
https://developer.wordpress.org/reference/hooks/pre_get_posts/

`pre_get_posts` runs after a query object is created and before it executes.
The official guidance requires checking `is_admin()` and using the passed
query object's `is_main_query()` method. This lets the policy alter only the
front-end main search or feed query while leaving administration and secondary
queries unchanged.

### Post-type sitemap membership

Sources:

- https://developer.wordpress.org/reference/classes/wp_sitemaps_posts/get_object_subtypes/
- https://developer.wordpress.org/reference/hooks/wp_sitemaps_posts_query_args/

`wp_sitemaps_post_types` filters the public post-type objects exposed by the
native posts sitemap provider. `wp_sitemaps_posts_query_args` filters the
query arguments for a retained post type. The first hook removes the inherited
`robot` subtype. The second can exclude exact default post and page IDs without
removing future editorial or approved catalog records.

### Taxonomy sitemap membership

Sources:

- https://developer.wordpress.org/reference/hooks/wp_sitemaps_taxonomies/
- https://developer.wordpress.org/reference/hooks/wp_sitemaps_taxonomies_query_args/

`wp_sitemaps_taxonomies` filters the public taxonomy objects exposed by the
native taxonomy sitemap provider. The query-argument hook supports excluding
the exact Uncategorized term while preserving future reviewed editorial
categories and product taxonomies.

### User sitemap provider

Sources:

- https://developer.wordpress.org/reference/classes/wp_sitemaps_registry/add_provider/
- https://developer.wordpress.org/reference/hooks/wp_sitemaps_users_query_args/

Every native provider passes through `wp_sitemaps_add_provider` before it is
registered. Returning a value that is not a `WP_Sitemaps_Provider` prevents
that provider from being added. This is the direct reversible control for the
users provider and its author URLs.

### Direct REST record requests

Source:
https://developer.wordpress.org/reference/hooks/rest_pre_dispatch/

`rest_pre_dispatch` receives the current result, REST server, and request
before the endpoint callback runs. Returning a non-empty result serves that
result instead. The policy uses the documented three-argument contract only
for exact inherited `GET` and `HEAD` detail routes. It returns a generic 404
for public requests, leaves write methods to WordPress core, and preserves
resource-specific editorial capabilities.

### Robots metadata

Sources:

- https://developer.wordpress.org/reference/hooks/wp_robots/
- https://developer.wordpress.org/reference/functions/wp_robots_no_robots/
- https://rankmath.com/docs/filters-and-hooks/frontend/meta-data/

`wp_robots` receives an associative array of directives. WordPress core's
`wp_robots_no_robots()` implementation sets `noindex` and, on a public site,
sets `follow`. The RobbottX policy follows the same directive shape for exact
inherited singular and archive contexts. Rank Math documents its separate
`rank_math/frontend/robots` array filter, so the policy must normalize the same
decision into Rank Math's string-valued directive shape when that plugin owns
the rendered robots metadata.

### Root robots.txt limitation

Source:
https://developer.wordpress.org/reference/functions/do_robots/

WordPress exposes a `robots_txt` filter only when the request reaches the
WordPress virtual robots handler. Production currently returns an nginx 404
for `/robots.txt`, so source code alone cannot prove that this hook controls the
root path. The release must preserve this as a live infrastructure limitation
until a literal `https://robbottx.com/robots.txt` request returns the intended
content with HTTP 200.

## Acceptance interpretation

- The inherited database rows remain unchanged and recoverable.
- Public search, feeds, REST discovery, direct REST details, and native sitemap
  providers stop disclosing them.
- Direct inherited URLs receive `noindex,follow` until URL-specific redirect or
  removal evidence is reviewed.
- Administration, authorized REST access, cron, commerce, accounts, media, and
  approved RobbottX post types remain outside the policy.
- Production truth comes from independent requests after deployment, not from
  hook registration or callback response text.
