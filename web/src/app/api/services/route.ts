import { NextRequest } from "next/server";
import { db } from "@/db";
import { tlsTalos, tlsCommerceServices } from "@/db/schema";
import { and, asc, desc, eq, gte, ilike, lt, lte, ne, or } from "drizzle-orm";

const VALID_SORT = ["price_asc", "price_desc", "newest"] as const;
type SortOrder = (typeof VALID_SORT)[number];

// GET /api/services — Discover available services across all TALOS agents
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;
    const category = searchParams.get("category");
    const selfId = searchParams.get("self");
    const cursor = searchParams.get("cursor");
    const limit = Math.min(Math.max(parseInt(searchParams.get("limit") ?? "50", 10) || 50, 1), 100);

    // Price range — reject reversed ranges explicitly
    const minPriceRaw = searchParams.get("minPrice");
    const maxPriceRaw = searchParams.get("maxPrice");
    const minPrice = minPriceRaw !== null ? parseFloat(minPriceRaw) : null;
    const maxPrice = maxPriceRaw !== null ? parseFloat(maxPriceRaw) : null;

    if (minPrice !== null && isNaN(minPrice)) {
      return Response.json({ error: "minPrice must be a number" }, { status: 400 });
    }
    if (maxPrice !== null && isNaN(maxPrice)) {
      return Response.json({ error: "maxPrice must be a number" }, { status: 400 });
    }
    if (minPrice !== null && minPrice < 0) {
      return Response.json({ error: "minPrice must be non-negative" }, { status: 400 });
    }
    if (maxPrice !== null && maxPrice < 0) {
      return Response.json({ error: "maxPrice must be non-negative" }, { status: 400 });
    }
    if (minPrice !== null && maxPrice !== null && minPrice > maxPrice) {
      return Response.json({ error: "minPrice cannot be greater than maxPrice" }, { status: 400 });
    }

    // Sort order — default newest; price sorts disable shuffle for stable ordering
    const sortRaw = searchParams.get("sortBy") ?? "newest";
    const sortBy: SortOrder = (VALID_SORT as readonly string[]).includes(sortRaw)
      ? (sortRaw as SortOrder)
      : "newest";

    const conditions = [];

    if (selfId) {
      conditions.push(ne(tlsCommerceServices.talosId, selfId));
    }

    if (category) {
      conditions.push(ilike(tlsTalos.category, category));
    }

    if (minPrice !== null) {
      conditions.push(gte(tlsCommerceServices.price, String(minPrice)));
    }

    if (maxPrice !== null) {
      conditions.push(lte(tlsCommerceServices.price, String(maxPrice)));
    }

    // Cursor pagination is only supported for the default (newest) sort.
    // Price-sorted requests return the full filtered page without a cursor.
    if (sortBy === "newest" && cursor) {
      const [cursorDate, cursorId] = cursor.split("|");
      if (cursorDate && cursorId) {
        conditions.push(
          or(
            lt(tlsCommerceServices.createdAt, new Date(cursorDate)),
            and(
              eq(tlsCommerceServices.createdAt, new Date(cursorDate)),
              lt(tlsCommerceServices.id, cursorId),
            ),
          )!,
        );
      }
    }

    const orderClauses =
      sortBy === "price_asc"
        ? [asc(tlsCommerceServices.price), asc(tlsCommerceServices.id)]
        : sortBy === "price_desc"
        ? [desc(tlsCommerceServices.price), asc(tlsCommerceServices.id)]
        : [desc(tlsCommerceServices.createdAt), desc(tlsCommerceServices.id)];

    const services = await db
      .select({
        id: tlsCommerceServices.id,
        talosId: tlsCommerceServices.talosId,
        talosName: tlsTalos.name,
        talosCategory: tlsTalos.category,
        serviceName: tlsCommerceServices.serviceName,
        description: tlsCommerceServices.description,
        price: tlsCommerceServices.price,
        currency: tlsCommerceServices.currency,
        chains: tlsCommerceServices.chains,
        createdAt: tlsCommerceServices.createdAt,
      })
      .from(tlsCommerceServices)
      .innerJoin(tlsTalos, eq(tlsCommerceServices.talosId, tlsTalos.id))
      .where(conditions.length > 0 ? and(...conditions) : undefined)
      .orderBy(...orderClauses)
      .limit(limit + 1);

    const hasMore = services.length > limit;
    const page = hasMore ? services.slice(0, limit) : services;

    const mapped = page.map((s) => ({
      talosId: s.talosId,
      talosName: s.talosName,
      talosCategory: s.talosCategory,
      serviceName: s.serviceName,
      description: s.description,
      price: Number(s.price),
      currency: s.currency,
      chains: s.chains,
    }));

    // Shuffle for diversity only when not sorting by price
    if (sortBy === "newest") {
      for (let i = mapped.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [mapped[i], mapped[j]] = [mapped[j], mapped[i]];
      }
    }

    const lastItem = page[page.length - 1];
    const nextCursor =
      hasMore && lastItem && sortBy === "newest"
        ? `${lastItem.createdAt.toISOString()}|${lastItem.id}`
        : null;

    return Response.json({ data: mapped, nextCursor });
  } catch {
    return Response.json({ error: "Internal server error" }, { status: 500 });
  }
}
