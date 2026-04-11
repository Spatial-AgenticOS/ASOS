@rem Gradle wrapper script for Windows
@if "%DEBUG%"=="" @echo off
setlocal
set DEFAULT_JVM_OPTS="-Xmx64m" "-Xms64m"
set DIRNAME=%~dp0
set APP_BASE_NAME=%~n0
set APP_HOME=%DIRNAME%
set CLASSPATH=%APP_HOME%\gradle\wrapper\gradle-wrapper.jar
set JAVACMD=java
if defined JAVA_HOME set JAVACMD=%JAVA_HOME%\bin\java
"%JAVACMD%" %DEFAULT_JVM_OPTS% -classpath "%CLASSPATH%" org.gradle.wrapper.GradleWrapperMain %*
