from fastapi import APIRouter, Request
import config

router = APIRouter()

@router.get("/servers")
async def servers(request: Request):
    guilds = []
    bot = config.bot
    if bot:
        for g in bot.guilds:
            guilds.append({
                "id": str(g.id),
                "name": g.name,
                "member_count": g.member_count,
                "icon": str(g.icon.url) if g.icon else None,
                "owner": {
                    "display_name": g.owner.display_name if g.owner else "Unknown",
                    "username": g.owner.name if g.owner else "Unknown",
                    "id": str(g.owner.id) if g.owner else "0",
                    "avatar": str(g.owner.display_avatar.url) if (g.owner and g.owner.display_avatar) else "",
                    "created_at": g.owner.created_at.strftime('%B %d, %Y') if g.owner else "N/A"
                },
                "created": g.created_at.strftime('%B %d, %Y') if g.created_at else "N/A"
            })
    return guilds

