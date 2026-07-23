<?php
/**
 * Title: Precision Atlas homepage
 * Slug: robbottx/home-precision-atlas
 * Categories: robbottx
 * Inserter: no
 */
?>
<!-- wp:html -->
<section class="rbtx-hero" id="atlas">
  <div class="rbtx-hero-inner">
    <div class="rbtx-hero-copy-block">
      <p class="rbtx-eyebrow">Robotics systems and components</p>
      <h1>Robotics, <span>mapped to evidence.</span></h1>
      <p class="rbtx-hero-copy">RobbottX brings together robotics systems, components, software, compatibility records, and technical documents in one technical atlas.</p>
      <form class="rbtx-search" id="atlas-search" role="search" method="get" action="/">
        <label>
          <span class="screen-reader-text">Search the RobbottX atlas</span>
          <input name="s" type="search" placeholder="Search RobbottX" autocomplete="off">
        </label>
        <button type="submit">Search</button>
      </form>
    </div>
    <div class="rbtx-atlas-figure" aria-label="Robotics system map from mission to technical documents and supply">
      <div class="rbtx-orbit"></div>
      <div class="rbtx-orbit rbtx-orbit--two"></div>
      <div class="rbtx-orbit rbtx-orbit--three"></div>
      <div class="rbtx-atlas-core"><span>System configuration</span><strong>System layers<br>in one view.</strong></div>
      <div class="rbtx-node rbtx-node--mission rbtx-node--verified"><small>01 Mission</small><strong>Mobile manipulation</strong></div>
      <div class="rbtx-node rbtx-node--system rbtx-node--verified"><small>02 System</small><strong>TurtleBot3 + arm</strong></div>
      <div class="rbtx-node rbtx-node--module"><small>03 Modules</small><strong>Base, arm, controller</strong></div>
      <div class="rbtx-node rbtx-node--software"><small>04 Software</small><strong>ROS 2 Humble</strong></div>
      <div class="rbtx-node rbtx-node--evidence rbtx-node--verified"><small>05 Documents</small><strong>Manufacturer sources</strong></div>
      <div class="rbtx-node rbtx-node--offer"><small>06 Supply</small><strong>Availability not confirmed</strong></div>
    </div>
    <div class="rbtx-hero-trust" aria-label="RobbottX record coverage">
      <div><strong>Technical records</strong><span>Manufacturer specifications use normalized units and appear with the source document list.</span></div>
      <div><strong>Compatibility by layer</strong><span>Mechanical, electrical, software, safety, and supply states stay separate.</span></div>
      <div><strong>Supply status</strong><span>Supplier, region, price, stock, and lead time are not confirmed for this configuration.</span></div>
    </div>
  </div>
</section>

<section class="rbtx-intents" aria-labelledby="rbtx-intents-title">
  <div class="rbtx-section-heading">
    <div>
      <p class="rbtx-eyebrow">Explore RobbottX</p>
      <h2 id="rbtx-intents-title">Find the level of detail your decision needs.</h2>
    </div>
    <p>Move from a system overview to exact specifications, compatibility conditions, source documents, and lifecycle context.</p>
  </div>
  <div class="rbtx-intent-grid">
    <a class="rbtx-intent-card" href="#featured-configuration"><span>01 / Explore</span><h3>Explore systems</h3><p>Move from robot to modules, components, software, documents, and lifecycle information.</p><span class="rbtx-intent-arrow" aria-hidden="true">↘</span></a>
    <a class="rbtx-intent-card" href="#verify"><span>02 / Compare</span><h3>Compare specifications</h3><p>Review normalized values with the conditions and source context that apply.</p><span class="rbtx-intent-arrow" aria-hidden="true">↘</span></a>
    <a class="rbtx-intent-card" href="#verify"><span>03 / Compatibility</span><h3>Review compatibility</h3><p>Check mechanical, electrical, protocol, software, safety, and supply conditions separately.</p><span class="rbtx-intent-arrow" aria-hidden="true">↘</span></a>
    <a class="rbtx-intent-card" href="#methodology"><span>04 / Documents</span><h3>Open source documents</h3><p>Review each publisher, document location, manufacturer link, and checksum prefix.</p><span class="rbtx-intent-arrow" aria-hidden="true">↘</span></a>
  </div>
</section>
<!-- /wp:html -->
