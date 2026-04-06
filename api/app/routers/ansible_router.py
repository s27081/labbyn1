"""Router for Ansible playbooks.

Creating Ansible user, gathering platform information and deploying Node Exporter.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import RequestContext
from app.core.exceptions import ExternalServiceError, ValidationError
from app.database import get_async_db
from app.db.models import CPUs, Disks, Machines, Metadata, Rooms
from app.db.schemas import AnsiblePlaybook, DiscoveryRequest, HostRequest
from app.utils.ansible_service import parse_platform_report, run_playbook_task
from app.utils.redis_service import acquire_lock

router = APIRouter(tags=["Ansible"])

REPORTS_DIR = "./platform_reports"
PLAYBOOK_DIR = "/code/ansible"

PLAYBOOK_MAP = {
    AnsiblePlaybook.create_user: f"{PLAYBOOK_DIR}/create_ansible_user.yaml",
    AnsiblePlaybook.scan_platform: f"{PLAYBOOK_DIR}/scan_platform.yaml",
    AnsiblePlaybook.deploy_agent: f"{PLAYBOOK_DIR}/deploy_agent.yaml",
    AnsiblePlaybook.delete_agent: f"{PLAYBOOK_DIR}/delete_agent.yaml",
    AnsiblePlaybook.delete_ansible: f"{PLAYBOOK_DIR}/delete_ansible.yaml",
}


@router.post("/ansible/create_user")
async def create_ansible_user(
    request: HostRequest, ctx: RequestContext = Depends(RequestContext.create)
):
    """Create Ansible user on a host.

    :param request: HostRequest containing the host IP or hostname
    :param ctx: Request context for user and team info
    :return: Success or error message.
    """
    ctx.require_user()
    try:
        return await run_playbook_task(
            PLAYBOOK_MAP[AnsiblePlaybook.create_user], request.host, request.extra_vars
        )
    except Exception as e:
        raise ExternalServiceError(
            f"Ansible (User Creation: {request.host}) failed", str(e)
        ) from e


@router.post("/ansible/scan_platform")
async def scan_platform(
    request: HostRequest, ctx: RequestContext = Depends(RequestContext.create)
):
    """Gather information about platform.

    :param request: HostRequest containing the host IP or hostname
    :param ctx: Request context for user and team info
    :return: Success or error message.
    """
    ctx.require_user()
    try:
        return await run_playbook_task(
            PLAYBOOK_MAP[AnsiblePlaybook.scan_platform],
            request.host,
            request.extra_vars,
        )
    except Exception as e:
        raise ExternalServiceError(
            f"Ansible (Platform Scan: {request.host}) failed", str(e)
        ) from e


@router.post("/ansible/deploy_agent")
async def deploy_agent(
    request: HostRequest, ctx: RequestContext = Depends(RequestContext.create)
):
    """Deploy Node Exporter on a host.

    :param request: HostRequest containing the host IP or hostname
    :param ctx: Request context for user and team info
    :return: Success or error message.
    """
    ctx.require_user()
    try:
        return await run_playbook_task(
            PLAYBOOK_MAP[AnsiblePlaybook.deploy_agent], request.host, request.extra_vars
        )
    except Exception as e:
        raise ExternalServiceError(
            f"Node Exporter (Prometheus Deployment: {request.host}) failed", str(e)
        ) from e


@router.post("/ansible/setup_agent")
async def setup_agent(
    request: HostRequest, ctx: RequestContext = Depends(RequestContext.create)
):
    """Create Ansible user (if needed), then deploy Node Exporter.

    :param request: HostRequest containing the host IP or hostname
    :param ctx: Request context for user and team info
    :return: Combined results of both steps.
    """
    ctx.require_user()

    try:
        user_result = await run_playbook_task(
            PLAYBOOK_MAP[AnsiblePlaybook.create_user], request.host, request.extra_vars
        )

        deploy_result = await run_playbook_task(
            PLAYBOOK_MAP[AnsiblePlaybook.deploy_agent], request.host, request.extra_vars
        )
        return {
            "user_creation": user_result,
            "node_exporter_deployment": deploy_result,
        }
    except Exception as e:
        raise ExternalServiceError(
            f"Ansible + Prometheus Workflow ({request.host}) failed", str(e)
        ) from e


@router.post("/ansible/discovery")
async def discover_hosts(
    request: DiscoveryRequest,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Discover hosts not connected to database.

    :param request: DiscoveryRequest containing the host IP or hostname
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Success or error message.
    """
    ctx.require_user()
    if not request.hosts:
        raise ValidationError("Host list cannot be empty.")

    target_team_id = request.target_team_id
    if not target_team_id:
        if len(ctx.team_ids) == 1:
            target_team_id = ctx.team_ids[0]
        else:
            raise ValidationError("Target team ID required.")

    await ctx.validate_team_access(target_team_id)

    try:
        await run_playbook_task(
            PLAYBOOK_MAP[AnsiblePlaybook.scan_platform],
            request.hosts,
            request.extra_vars,
        )
    except Exception as e:
        hosts_str = ", ".join(request.hosts)
        raise ExternalServiceError(
            f"Ansible Discovery Scan for hosts [{hosts_str}] failed", str(e)
        ) from e

    results = []
    res_room = await db.execute(
        select(Rooms).filter(Rooms.name == "virtual", Rooms.team_id == target_team_id)
    )
    default_room = res_room.scalar_one_or_none()

    if not default_room:
        default_room = Rooms(
            name="virtual", room_type="virtual", team_id=target_team_id
        )
        db.add(default_room)
        await db.commit()
        await db.refresh(default_room)

    for host in request.hosts:
        try:
            specs = parse_platform_report(host)
            stmt = select(Machines).filter(Machines.name == host)
            stmt = ctx.team_filter(stmt, Machines)
            m_res = await db.execute(stmt)
            machine = m_res.scalar_one_or_none()

            if machine:
                for field in ["os", "ram", "mac_address", "ip_address"]:
                    setattr(machine, field, specs.get(field))

                await db.execute(delete(CPUs).where(CPUs.machine_id == machine.id))
                for cpu_data in specs.get("cpus", []):
                    db.add(CPUs(name=cpu_data["name"], machine_id=machine.id))

                await db.execute(delete(Disks).where(Disks.machine_id == machine.id))
                for disk_data in specs.get("disks", []):
                    db.add(
                        Disks(
                            name=disk_data["name"],
                            capacity=disk_data.get("capacity"),
                            machine_id=machine.id,
                        )
                    )

                meta_res = await db.execute(
                    select(Metadata).where(Metadata.id == machine.metadata_id)
                )
                meta = meta_res.scalar_one_or_none()
                if meta:
                    meta.ansible_access = True
                    meta.agent_prometheus = specs["agent_prometheus"]
                    meta.last_update = datetime.now()
                results.append({"host": host, "status": "updated"})
            else:
                new_meta = Metadata(
                    last_update=datetime.now(),
                    agent_prometheus=specs["agent_prometheus"],
                    ansible_access=True,
                    ansible_root_access=True,
                )
                db.add(new_meta)
                await db.flush()

                new_machine = Machines(
                    name=host,
                    team_id=target_team_id,
                    metadata_id=new_meta.id,
                    localization_id=default_room.id,
                    os=specs["os"],
                    ram=specs["ram"],
                    mac_address=specs["mac_address"],
                    ip_address=host,
                    added_on=datetime.now(),
                )
                db.add(new_machine)
                await db.flush()

                for cpu_data in specs.get("cpus", []):
                    db.add(CPUs(name=cpu_data["name"], machine_id=new_machine.id))
                for disk_data in specs.get("disks", []):
                    db.add(
                        Disks(
                            name=disk_data["name"],
                            capacity=disk_data.get("capacity"),
                            machine_id=new_machine.id,
                        )
                    )
                results.append({"host": host, "status": "created"})

        except Exception as e:
            results.append(
                {
                    "host": host,
                    "status": "error",
                    "detail": f"Data processing for {host} failed: {str(e)}",
                }
            )

    await db.commit()
    return {"summary": results}


@router.post("/ansible/machine/{machine_id}/refresh")
async def refresh_machine_hardware(
    request: HostRequest,
    machine_id: int,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Refresh information about machine hardware.

    :param request: DiscoveryRequest containing the host IP or hostname
    :param machine_id: Machine ID
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Success or error message.
    """
    stmt = select(Machines).filter(Machines.id == machine_id)
    machine = (await db.execute(ctx.team_filter(stmt, Machines))).scalar_one_or_none()

    try:
        await run_playbook_task(
            PLAYBOOK_MAP[AnsiblePlaybook.scan_platform],
            [machine.name],
            request.extra_vars,
        )
        specs = parse_platform_report(machine.name)
        for field in ["os", "ram", "mac_address", "ip_address", "name"]:
            setattr(machine, field, specs.get(field))

        await db.execute(delete(CPUs).where(CPUs.machine_id == machine.id))
        for cpu_data in specs.get("cpus", []):
            db.add(CPUs(name=cpu_data["name"], machine_id=machine.id))

        await db.execute(delete(Disks).where(Disks.machine_id == machine.id))
        for disk_data in specs.get("disks", []):
            db.add(
                Disks(
                    name=disk_data["name"],
                    capacity=disk_data.get("capacity"),
                    machine_id=machine.id,
                )
            )

        meta_res = await db.execute(
            select(Metadata).where(Metadata.id == machine.metadata_id)
        )
        meta = meta_res.scalar_one_or_none()
        if meta:
            meta.ansible_access = True
            meta.agent_prometheus = specs["agent_prometheus"]
            meta.last_update = datetime.now()

        await db.commit()
        return {
            "message": f"Hardware for {machine.name} refreshed successfully",
            "data": specs,
        }
    except Exception as e:
        await db.rollback()
        raise ExternalServiceError(
            f"Hardware Refresh for {machine.name} failed", str(e)
        ) from e


@router.post("/ansible/machine/{machine_id}/cleanup")
async def cleanup_machine(
    machine_id: int,
    request: HostRequest,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete Ansible/Node exporters from machine.

    :param machine_id: Machine ID
    :param request: DiscoveryRequest containing the host IP or hostname
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Success or error message.
    """
    async with acquire_lock(f"machine_lock:{machine_id}"):
        stmt = select(Machines).filter(Machines.id == machine_id)
        machine = (
            await db.execute(ctx.team_filter(stmt, Machines))
        ).scalar_one_or_none()
        try:
            agent_res = await run_playbook_task(
                PLAYBOOK_MAP[AnsiblePlaybook.delete_agent],
                machine.name,
                request.extra_vars,
            )
            ansible_res = await run_playbook_task(
                PLAYBOOK_MAP[AnsiblePlaybook.delete_ansible],
                machine.name,
                request.extra_vars,
            )

            meta_res = await db.execute(
                select(Metadata).where(Metadata.id == machine.metadata_id)
            )
            meta = meta_res.scalar_one_or_none()
            if meta:
                meta.ansible_access = False
                meta.ansible_root_access = False
                meta.agent_prometheus = False
                meta.last_update = datetime.now()

            await db.commit()
            return {
                "message": f"Cleanup for {machine.name} completed",
                "agent": agent_res,
                "ansible": ansible_res,
            }
        except Exception as e:
            await db.rollback()
            raise ExternalServiceError(
                f"Ansible Cleanup for {machine.name} failed", str(e)
            ) from e


@router.post("/ansible/machine/{machine_id}/remove_agent")
async def remove_agent(
    machine_id: int,
    request: HostRequest,
    db: AsyncSession = Depends(get_async_db),
    ctx: RequestContext = Depends(RequestContext.create),
):
    """Delete Node exporter from machine.

    :param machine_id: Machine ID
    :param request: DiscoveryRequest containing the host IP or hostname
    :param db: Active database session
    :param ctx: Request context for user and team info
    :return: Success or error message.
    """
    async with acquire_lock(f"machine_lock:{machine_id}"):
        stmt = select(Machines).filter(Machines.id == machine_id)
        machine = (
            await db.execute(ctx.team_filter(stmt, Machines))
        ).scalar_one_or_none()
        try:
            agent_res = await run_playbook_task(
                PLAYBOOK_MAP[AnsiblePlaybook.delete_agent],
                machine.name,
                request.extra_vars,
            )
            meta_res = await db.execute(
                select(Metadata).where(Metadata.id == machine.metadata_id)
            )
            meta = meta_res.scalar_one_or_none()
            if meta:
                meta.agent_prometheus = False
                meta.last_update = datetime.now()

            await db.commit()
            return {
                "message": f"Agent removed from {machine.name}",
                "agent_result": agent_res,
            }
        except Exception as e:
            await db.rollback()
            raise ExternalServiceError(
                f"Agent Removal for {machine.name} failed"
            ) from e
