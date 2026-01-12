import js from '@eslint/js';
import tseslint from 'typescript-eslint'; // 推荐使用 typescript-eslint 工具包
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

export default tseslint.config(
  {
    // 忽略项：增加针对 Vite 常用目录的忽略
    ignores: ['dist', 'node_modules', 'public', '.vscode'],
  },
  {
    // 继承推荐配置
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommendedTypeChecked, // 开启“类型感应”检查
    ],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: {
        project: ['./tsconfig.json'], // 核心：关联 TS 配置
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      'react': react,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    settings: {
      react: { version: 'detect' }, // 自动检测 React 版本
    },
    rules: {
      // --- AI 友好型规则 ---
      
      // 1. 允许变量未使用（交由 IDE 显示灰色，但不报红），AI 经常生成中间变量
      '@typescript-eslint/no-unused-vars': 'off', 
      
      // 2. 既然你配置了 noImplicitAny: true，这里允许显式 any 作为逃生舱
      '@typescript-eslint/no-explicit-any': 'warn', 
      
      // 3. 严格禁止 Hooks 依赖遗漏，这是 AI 最容易写出 Bug 的地方
      ...reactHooks.configs.recommended.rules,
      'react-hooks/exhaustive-deps': 'error',

      // 4. 针对现代 React 优化的规则
      'react/react-in-jsx-scope': 'off', // React 17+ 不需要 import React
      'react/prop-types': 'off',         // 有 TS 了，不需要 PropTypes
      
      // 5. 提醒 AI 别留下调试代码
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-debugger': 'warn',

      // 6. Vite 专属规则
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  }
);