---
name: Rimi photo metadata
description: Current Rimi product pages may expose product images only through social metadata, with a Cloudinary fallback that requires verification.
---

Rimi product pages can have no product `<img>` elements while still declaring an `og:image` Cloudinary URL. A fallback transformation inside that URL can silently serve a generic image if the underlying asset is missing; remove the fallback segment and require a successful image response before treating it as a real product photo.

**Why:** A photo-only recovery found pages with valid titles but no usable image tags, even though their metadata images were real. The fallback URL alone does not prove the product asset exists.

**How to apply:** When improving ordinary product-photo scraping or auditing stored photo URLs, inspect metadata as well as image tags and verify that the Cloudinary asset resolves without the fallback transformation.