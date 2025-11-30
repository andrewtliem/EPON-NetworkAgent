from typing import Any
from typing_extensions import override

from google.adk.tools.agent_tool import AgentTool
from google.adk.tools import ToolContext
from google.genai import types
from google.adk.utils.context_utils import Aclosing

from epon_adk.utils.event_logger import log_adk_event

class LoggingAgentTool(AgentTool):
    """
    A subclass of AgentTool that logs events to the shared event logger.
    """

    @override
    async def run_async(
        self,
        *,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Any:
        from google.adk.agents.llm_agent import LlmAgent
        from google.adk.runners import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
        from google.adk.tools._forwarding_artifact_service import ForwardingArtifactService

        if self.skip_summarization:
            tool_context.actions.skip_summarization = True

        if isinstance(self.agent, LlmAgent) and self.agent.input_schema:
            input_value = self.agent.input_schema.model_validate(args)
            content = types.Content(
                role='user',
                parts=[
                    types.Part.from_text(
                        text=input_value.model_dump_json(exclude_none=True)
                    )
                ],
            )
        else:
            content = types.Content(
                role='user',
                parts=[types.Part.from_text(text=args['request'])],
            )
        invocation_context = tool_context._invocation_context
        parent_app_name = (
            invocation_context.app_name if invocation_context else None
        )
        child_app_name = parent_app_name or self.agent.name
        runner = Runner(
            app_name=child_app_name,
            agent=self.agent,
            artifact_service=ForwardingArtifactService(tool_context),
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
            credential_service=tool_context._invocation_context.credential_service,
            plugins=list(tool_context._invocation_context.plugin_manager.plugins),
        )

        state_dict = {
            k: v
            for k, v in tool_context.state.to_dict().items()
            if not k.startswith('_adk')  # Filter out adk internal states
        }
        session = await runner.session_service.create_session(
            app_name=child_app_name,
            user_id=tool_context._invocation_context.user_id,
            state=state_dict,
        )

        last_content = None
        async with Aclosing(
            runner.run_async(
                user_id=session.user_id, session_id=session.id, new_message=content
            )
        ) as agen:
            async for event in agen:
                # --- LOGGING INJECTION ---
                log_adk_event(event)
                # -------------------------

                # Forward state delta to parent session.
                if event.actions.state_delta:
                    tool_context.state.update(event.actions.state_delta)
                if event.content:
                    last_content = event.content

        if not last_content:
            return ''
        merged_text = '\n'.join(p.text for p in last_content.parts if p.text)
        if isinstance(self.agent, LlmAgent) and self.agent.output_schema:
            tool_result = self.agent.output_schema.model_validate_json(
                merged_text
            ).model_dump(exclude_none=True)
        else:
            tool_result = merged_text
        return tool_result
