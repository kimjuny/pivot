import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getAgents } from '../utils/api';
import { formatTimestamp } from '../utils/timestamp';
import type { Agent } from '../types';

function AgentList() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    loadAgents();
  }, []);

  const loadAgents = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getAgents();
      setAgents(data);
    } catch (err) {
      const error = err as Error;
      setError(error.message || 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateAgent = () => {
    console.log('Create agent button clicked (not implemented yet)');
  };

  const handleAgentClick = (agent: Agent) => {
    navigate(`/agent/${agent.id}`);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-dark-bg">
        <div className="flex flex-col items-center space-y-4">
          <div className="spinner"></div>
          <div className="text-lg text-dark-text-secondary font-medium">加载中...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-dark-bg">
        <div className="text-xl text-red-400 mb-4 font-medium">错误: {error}</div>
        <button
          onClick={loadAgents}
          className="px-6 py-3 btn-accent rounded-lg font-medium"
        >
          重试
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-dark-bg text-dark-text-primary">
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-dark-text-primary">Agent 列表</h1>
            <p className="text-dark-text-secondary mt-2">管理您的所有 Agent 实例</p>
          </div>
          <button
            onClick={handleCreateAgent}
            className="flex items-center space-x-2 px-4 py-2 btn-accent rounded-lg font-medium"
            title="创建新的 Agent"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H8m8 8v16m8-8h-8m8 8v16m8-8H8m8 8v16" />
            </svg>
            <span>创建 Agent</span>
          </button>
        </div>

        {agents.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-6xl text-dark-text-muted mb-4">📭</div>
            <h3 className="text-xl font-semibold text-dark-text-secondary mb-2">暂无 Agent</h3>
            <p className="text-dark-text-muted mb-6">
              点击右上角的"创建 Agent"按钮来创建您的第一个 Agent
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {agents.map((agent) => (
              <div
                key={agent.id}
                onClick={() => handleAgentClick(agent)}
                className="card-subtle rounded-xl p-6 cursor-pointer hover:shadow-lg transition-all duration-200"
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center space-x-3">
                    <div className="w-12 h-12 rounded-lg bg-primary/20 flex items-center justify-center">
                      <svg className="w-6 h-6 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1H8l-1 1h8l-1 1H9l.75 17z" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-dark-text-primary">{agent.name}</h3>
                      <div className="flex items-center space-x-2 mt-1">
                        <span className={`status-dot ${agent.is_active ? 'active' : ''}`}></span>
                        <span className="text-sm text-dark-text-secondary">
                          {agent.is_active ? '活跃' : '未激活'}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="text-xs text-dark-text-muted">
                    ID: {agent.id}
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center space-x-2 text-sm">
                    <svg className="w-4 h-4 text-dark-text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16m-7 6h7" />
                    </svg>
                    <span className="text-dark-text-secondary">模型:</span>
                    <span className="text-dark-text-primary font-medium">{agent.model_name || 'N/A'}</span>
                  </div>

                  <div className="flex items-center space-x-2 text-sm">
                    <svg className="w-4 h-4 text-dark-text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3l3-3" />
                    </svg>
                    <span className="text-dark-text-secondary">创建时间:</span>
                    <span className="text-dark-text-primary font-medium">{formatTimestamp(agent.created_at)}</span>
                  </div>

                  {agent.description && (
                    <div className="flex items-start space-x-2 text-sm">
                      <svg className="w-4 h-4 text-dark-text-muted mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                      </svg>
                      <p className="text-dark-text-secondary line-clamp-2">{agent.description}</p>
                    </div>
                  )}
                </div>

                <div className="mt-4 pt-4 border-t border-dark-border">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-dark-text-muted">点击查看详情</span>
                    <svg className="w-5 h-5 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default AgentList;
