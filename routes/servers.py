from fastapi import APIRouter, Request
import config

router = APIRouter()

@router.get("")
async def list_servers(request: Request, page: int = 1, limit: int = 50):
    if page < 1:
        page = 1
    if limit < 1:
        limit = 50
    elif limit > 100:
        limit = 100

    guilds = []
    bot = request.app.state.bot
    if bot:
        sorted_guilds = sorted(bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paged_guilds = sorted_guilds[start_idx:end_idx]
        
        for g in paged_guilds:
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

