import asyncio
import json
import re
import structlog
from openai import AsyncOpenAI
from agents.base_agent import BaseAgent
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.repositories.analytics_repo import AnalyticsRepository

log = structlog.get_logger()

QUEUE_CAMPAIGN = "queue:campaign"

# Google Ads daily budget cap (USD) — shared across all campaigns
DAILY_BUDGET_USD = 50.0

# Niche → keyword templates
NICHE_KEYWORDS = {
    "plumber":      ["emergency plumber near me", "plumber {city}", "pipe repair {city}", "drain unclog {city}"],
    "roofer":       ["roof repair {city}", "roofer near me", "roofing contractor {city}", "roof replacement estimate"],
    "hvac":         ["hvac repair {city}", "air conditioner repair {city}", "furnace repair {city}", "hvac near me"],
    "pest control": ["pest control {city}", "exterminator near me", "bed bug removal {city}", "rodent control {city}"],
    "dentist":      ["dentist near me {city}", "teeth cleaning {city}", "emergency dentist {city}", "dental clinic {city}"],
    "cleaning":     ["house cleaning service {city}", "maid service {city}", "deep cleaning {city}"],
    "landscaping":  ["landscaping company {city}", "lawn care {city}", "garden service near me"],
    "renovation":   ["home renovation {city}", "kitchen remodel {city}", "bathroom renovation {city}"],
}
DEFAULT_KEYWORDS = ["{niche} near me", "best {niche} {city}", "{niche} service {city}", "affordable {niche} {city}"]


def _build_keywords(niche: str, city: str) -> list:
    templates = NICHE_KEYWORDS.get(niche.lower(), DEFAULT_KEYWORDS)
    return [t.replace("{city}", city).replace("{niche}", niche) for t in templates]


class CampaignAgent(BaseAgent):
    name = "campaign_agent"
    queue = QUEUE_CAMPAIGN

    def __init__(self):
        super().__init__()
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None

    # ------------------------------------------------------------------ #
    #  Google Ads client                                                   #
    # ------------------------------------------------------------------ #

    def _get_ads_client(self):
        from google.ads.googleads.client import GoogleAdsClient
        login_customer_id = self._normalize_customer_id(settings.GOOGLE_ADS_MANAGER_CUSTOMER_ID)
        credentials = {
            "developer_token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
            "client_id": settings.GOOGLE_ADS_CLIENT_ID,
            "client_secret": settings.GOOGLE_ADS_CLIENT_SECRET,
            "refresh_token": settings.GOOGLE_ADS_REFRESH_TOKEN,
            "login_customer_id": login_customer_id,
            "use_proto_plus": True,
        }
        return GoogleAdsClient.load_from_dict(credentials)

    def _validate_ads_settings(self) -> list:
        required = [
            "GOOGLE_ADS_DEVELOPER_TOKEN",
            "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET",
            "GOOGLE_ADS_REFRESH_TOKEN",
            "GOOGLE_ADS_MANAGER_CUSTOMER_ID",
            "GOOGLE_ADS_CUSTOMER_ID",
        ]
        missing = [name for name in required if not getattr(settings, name, None)]
        if missing:
            log.error("Campaign agent missing required settings", missing=missing)
        return missing

    @staticmethod
    def _normalize_customer_id(customer_id: str | None) -> str | None:
        if not customer_id:
            return None
        normalized = re.sub(r"[^0-9]", "", customer_id)
        return normalized or None

    def _get_or_create_campaign(self, client, customer_id: str, niche: str, city: str) -> str:
        """Create a Search campaign for niche+city. Returns resource name."""
        campaign_service = client.get_service("CampaignService")
        campaign_budget_service = client.get_service("CampaignBudgetService")
        ads_service = client.get_service("GoogleAdsService")
        campaign_name = f"LeadFlow360 | {niche.title()} | {city}"

        # Check if already exists
        query = f"""
            SELECT campaign.id, campaign.name, campaign.resource_name
            FROM campaign
            WHERE campaign.name = '{campaign_name}'
              AND campaign.status != 'REMOVED'
            LIMIT 1
        """
        response = ads_service.search(customer_id=customer_id, query=query)
        for row in response:
            log.info("Campaign exists", name=campaign_name)
            return row.campaign.resource_name

        # Create shared budget ($50/day)
        budget_op = client.get_type("CampaignBudgetOperation")
        budget = budget_op.create
        budget.name = f"LeadFlow360 Budget | {niche} | {city}"
        budget.amount_micros = int(DAILY_BUDGET_USD * 1_000_000)
        budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
        budget_resp = campaign_budget_service.mutate_campaign_budgets(
            customer_id=customer_id, operations=[budget_op]
        )
        budget_resource = budget_resp.results[0].resource_name

        # Create campaign
        from datetime import date
        campaign_op = client.get_type("CampaignOperation")
        c = campaign_op.create
        c.name = campaign_name
        c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
        c.status = client.enums.CampaignStatusEnum.ENABLED
        c.campaign_budget = budget_resource
        c.target_spend.cpc_bid_ceiling_micros = 3_000_000  # $3 max CPC
        c.geo_target_type_setting.positive_geo_target_type = (
            client.enums.PositiveGeoTargetTypeEnum.PRESENCE_OR_INTEREST
        )
        c.start_date = date.today().strftime("%Y%m%d")
        campaign_resp = campaign_service.mutate_campaigns(customer_id=customer_id, operations=[campaign_op])
        resource = campaign_resp.results[0].resource_name
        log.info("Campaign created", name=campaign_name, resource=resource)
        return resource

    def _create_ad_group(self, client, customer_id: str, campaign_resource: str, niche: str, city: str) -> str:
        ad_group_service = client.get_service("AdGroupService")
        op = client.get_type("AdGroupOperation")
        ag = op.create
        ag.name = f"LeadFlow360 AdGroup | {niche.title()} | {city}"
        ag.campaign = campaign_resource
        ag.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
        ag.cpc_bid_micros = 1_500_000  # $1.50 default CPC
        ag.status = client.enums.AdGroupStatusEnum.ENABLED
        resp = ad_group_service.mutate_ad_groups(customer_id=customer_id, operations=[op])
        resource = resp.results[0].resource_name
        log.info("Ad group created", resource=resource)
        return resource

    def _add_keywords(self, client, customer_id: str, ad_group_resource: str, keywords: list):
        ad_group_criterion_service = client.get_service("AdGroupCriterionService")
        ops = []
        for kw in keywords:
            op = client.get_type("AdGroupCriterionOperation")
            criterion = op.create
            criterion.ad_group = ad_group_resource
            criterion.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
            criterion.keyword.text = kw
            criterion.keyword.match_type = client.enums.KeywordMatchTypeEnum.BROAD
            ops.append(op)
        if ops:
            ad_group_criterion_service.mutate_ad_group_criteria(customer_id=customer_id, operations=ops)
            log.info("Keywords added", count=len(ops))

    def _create_responsive_search_ad(
        self, client, customer_id: str, ad_group_resource: str,
        headlines: list, descriptions: list, final_url: str
    ):
        ad_group_ad_service = client.get_service("AdGroupAdService")
        op = client.get_type("AdGroupAdOperation")
        aga = op.create
        aga.ad_group = ad_group_resource
        aga.status = client.enums.AdGroupAdStatusEnum.ENABLED
        rsa = aga.ad.responsive_search_ad
        for h in headlines[:15]:
            asset = client.get_type("AdTextAsset")
            asset.text = h[:30]
            rsa.headlines.append(asset)
        for d in descriptions[:4]:
            asset = client.get_type("AdTextAsset")
            asset.text = d[:90]
            rsa.descriptions.append(asset)
        aga.ad.final_urls.append(final_url)
        ad_group_ad_service.mutate_ad_group_ads(customer_id=customer_id, operations=[op])
        log.info("Responsive search ad created", url=final_url)

    # ------------------------------------------------------------------ #
    #  AI copy generation                                                  #
    # ------------------------------------------------------------------ #

    async def _generate_ad_copy(self, niche: str, city: str) -> dict:
        if not self.openai:
            return {}
        msg = await self.openai.chat.completions.create(
            model=settings.OPENAI_MODEL_FAST,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    f"Google Ads copy for {niche} lead gen service in {city}, Canada.\n"
                    "Return JSON: headlines (10 strings max 30 chars), descriptions (4 strings max 90 chars), "
                    "final_url_path (slug).\n"
                    "Focus: exclusive leads, pay per lead, verified customers, fast delivery."
                )
            }],
            response_format={"type": "json_object"},
        )
        return json.loads(msg.choices[0].message.content)

    # ------------------------------------------------------------------ #
    #  Performance reporting                                               #
    # ------------------------------------------------------------------ #

    async def _check_ads_performance(self, customer_id: str):
        try:
            client = self._get_ads_client()
            ads_service = client.get_service("GoogleAdsService")
            query = """
                SELECT
                  campaign.name,
                  metrics.impressions,
                  metrics.clicks,
                  metrics.cost_micros,
                  metrics.conversions
                FROM campaign
                WHERE segments.date DURING LAST_7_DAYS
                  AND campaign.status = 'ENABLED'
                ORDER BY metrics.cost_micros DESC
                LIMIT 20
            """
            response = ads_service.search(customer_id=customer_id, query=query)
            results = []
            for row in response:
                results.append({
                    "campaign": row.campaign.name,
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "cost_usd": round(row.metrics.cost_micros / 1_000_000, 2),
                    "conversions": row.metrics.conversions,
                })
            log.info("Ads performance 7d", results=results)
            return results
        except Exception as e:
            log.error("Ads performance error", error=str(e))
            return []

    # ------------------------------------------------------------------ #
    #  Main process                                                        #
    # ------------------------------------------------------------------ #

    async def process(self, payload: dict):
        action = payload.get("action")

        if action == "launch_campaign":
            if self._validate_ads_settings():
                return
            niche = payload.get("niche", "plumber")
            cities = payload.get("cities", settings.DISCOVERY_CITIES[:3])
            customer_id = self._normalize_customer_id(settings.GOOGLE_ADS_CUSTOMER_ID)

            if not customer_id:
                log.error("GOOGLE_ADS_CUSTOMER_ID not set")
                return

            for city in cities:
                try:
                    copy = await self._generate_ad_copy(niche, city)
                    headlines = copy.get("headlines", [
                        f"Top {niche.title()} in {city}", "Exclusive Leads Pay Per Lead", "Verified Buyers Daily"
                    ])
                    descriptions = copy.get("descriptions", [
                        f"Get verified {niche} leads in {city}. No subscriptions.",
                        "Exclusive leads delivered to your inbox daily.",
                    ])
                    url_path = copy.get("final_url_path", f"{niche.replace(' ','-')}-leads-{city.lower().replace(' ','-')}")
                    final_url = f"https://leadflow360.ca/{url_path}"
                    keywords = _build_keywords(niche, city)

                    client = self._get_ads_client()
                    campaign_resource = self._get_or_create_campaign(client, customer_id, niche, city)
                    ad_group_resource = self._create_ad_group(client, customer_id, campaign_resource, niche, city)
                    self._add_keywords(client, customer_id, ad_group_resource, keywords)
                    self._create_responsive_search_ad(client, customer_id, ad_group_resource, headlines, descriptions, final_url)
                    log.info("Google Ads campaign launched", niche=niche, city=city)
                except Exception as e:
                    log.error("Campaign launch error", niche=niche, city=city, error=str(e))

        elif action == "check_performance":
            customer_id = self._normalize_customer_id(settings.GOOGLE_ADS_CUSTOMER_ID)
            if customer_id:
                await self._check_ads_performance(customer_id)
            async with AsyncSessionLocal() as db:
                repo = AnalyticsRepository(db)
                revenue = await repo.daily_revenue()
                by_niche = await repo.revenue_by_niche()
                log.info("Internal performance", daily_revenue=revenue, by_niche=by_niche)

        elif action == "pause_campaign":
            niche = payload.get("niche")
            city = payload.get("city")
            customer_id = self._normalize_customer_id(settings.GOOGLE_ADS_CUSTOMER_ID)
            if not all([customer_id, niche, city]):
                return
            try:
                client = self._get_ads_client()
                ads_service = client.get_service("GoogleAdsService")
                campaign_name = f"LeadFlow360 | {niche.title()} | {city}"
                query = f"SELECT campaign.id, campaign.resource_name FROM campaign WHERE campaign.name = '{campaign_name}' LIMIT 1"
                response = ads_service.search(customer_id=customer_id, query=query)
                campaign_service = client.get_service("CampaignService")
                for row in response:
                    op = client.get_type("CampaignOperation")
                    op.update.resource_name = row.campaign.resource_name
                    op.update.status = client.enums.CampaignStatusEnum.PAUSED
                    op.update_mask.paths.append("status")
                    campaign_service.mutate_campaigns(customer_id=customer_id, operations=[op])
                    log.info("Campaign paused", name=campaign_name)
            except Exception as e:
                log.error("Pause campaign error", error=str(e))


if __name__ == "__main__":
    asyncio.run(CampaignAgent().run())
