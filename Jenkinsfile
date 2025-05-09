pipeline {
    agent {
        kubernetes {
            defaultContainer 'default'
            yaml """\
        apiVersion: v1
        kind: Pod
        metadata:
          labels:
            component: builder
            lang: python
            app: pg-listener-py
        spec:
          containers:
          - name: default
            image: image-registry.openshift-image-registry.svc:5000/vrt-intake/python:3.10
            command:
            - cat
            tty: true
          - name: oc
            image: image-registry.openshift-image-registry.svc:5000/ci-cd/py:3.7
            command:
            - cat
            tty: true
        """.stripIndent()
        }
    }

    options {
        timeout(time: 45, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    environment {
        APP_NAME   = 'pg-listener-py'
        OC_URL     = 'https://c113-e.private.eu-de.containers.cloud.ibm.com:30227'
        OC_PROJECT = 'vrt-intake'
        JIRA_URL   = 'meemoo.atlassian.net'
    }

    stages {
        stage('ENV') {
            steps {
                container('oc') {
                    script {
                        env.GIT_SHORT_COMMIT = sh(script: "printf \$(git rev-parse --short ${GIT_COMMIT})", returnStdout: true)
                        env.IMAGE_TAG = sh(script: 'git describe --tags || echo latest', returnStdout: true)
                        // the build config name is based on the image tag, replacing dots with dashes
                        env.BUILD_CONFIG_NAME = sh(script: 'echo "${IMAGE_TAG}" | sed -E "s/\\./-/g"', returnStdout: true)
                    }
                }
            }
        }

        stage('Test') {
            steps {
                sh 'make test'
            }
        }

        stage('Build') {
            when {
                not {
                    buildingTag()
                }
            }
            steps {
                container('oc') {
                    script {
                        sh '''
                            oc project $OC_PROJECT
                            oc set image-lookup python
                            oc new-build -l ref=$BRANCH_NAME --strategy=docker --name $APP_NAME-$GIT_SHORT_COMMIT --to $APP_NAME:$GIT_SHORT_COMMIT --binary --context-dir="" || echo Probably already exists, start new build
                            sleep 3
                            oc annotate --overwrite buildconfig/$APP_NAME-$GIT_SHORT_COMMIT ref=$BRANCH_NAME shortcommit=$GIT_SHORT_COMMIT
                            oc start-build $APP_NAME-$GIT_SHORT_COMMIT --from-dir=. --follow=true --wait=true
                        '''
                    }
                }
            }
        }

        stage('INT') {
            when {
                changeRequest target: 'main'
            }
            steps {
                container('oc') {
                    tagNewImage('int')
                }
            }
            post {
                always {
                    script {
                        env.BRANCH_NAME = env.CHANGE_BRANCH
                    }
                    jiraSendDeploymentInfo site: "${JIRA_URL}", environmentId: 'int', environmentName: 'int', environmentType: 'testing'
                }
            }
        }

        stage('QAS') {
            when {
                branch 'main'
            }
            steps {
                container('oc') {
                    tagNewImage('qas')
                }
            }
            post {
                always {
                    jiraSendDeploymentInfo site: "${JIRA_URL}", environmentId: 'qas', environmentName: 'qas', environmentType: 'staging'
                }
            }
        }

        stage('PRD') {
            when {
                buildingTag()
            }
            steps {
                container('oc') {
                    tagNewImage('prd')
                }
            }
            post {
                always {
                    jiraSendDeploymentInfo site: "${JIRA_URL}", environmentId: 'prd', environmentName: 'prd', environmentType: 'production'
                }
            }
        }
    }

    post {
        success {
            script {
                if (env.BRANCH_NAME.startsWith('PR')) {
                    setGitHubBuildStatus('Build', 'SUCCESS')
                }
            }
        }
        failure {
            script {
                if (env.BRANCH_NAME.startsWith('PR')) {
                    setGitHubBuildStatus('Build', 'FAILURE')
                }
            }
        }
        always {
            jiraSendBuildInfo site: "${JIRA_URL}"
            container('default') {
                // archive test results
                script {
                    if (fileExists('./tests/test_results.xml')) {
                        junit 'tests/test_results.xml'
                    } else {
                        echo 'No test results found'
                    }
                }
            }
        }
    }
}

void setGitHubBuildStatus(String message, String state) {
    step([
        $class: 'GitHubCommitStatusSetter',
        reposSource: [$class: 'ManuallyEnteredRepositorySource', url: "${GIT_URL}"],
        commitShaSource: [$class: 'ManuallyEnteredShaSource', sha: "${GIT_COMMIT}"],
        errorHandlers: [[$class: 'ChangingBuildStatusErrorHandler', result: 'UNSTABLE']],
        statusResultSource: [ $class: 'ConditionalStatusResultSource', results: [[$class: 'AnyBuildResult', message: message, state: state]] ]
    ])
}

void tagNewImage(String environment) {
    echo "Deploying to ${environment}"
    sh """
        oc project $OC_PROJECT
        oc tag $APP_NAME:$GIT_SHORT_COMMIT $APP_NAME:${environment}
        # check the status of the rollout
        oc rollout status deployment/$APP_NAME-${environment} --watch=true --timeout=10m
    """
}
