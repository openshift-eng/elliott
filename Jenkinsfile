@Library('art-ci-toolkit@master') _

pipeline {
    agent {
        docker {
            image "openshift-art/art-ci-toolkit:latest"
            alwaysPull true
            args "-e http_proxy -e https_proxy -e no_proxy -e HTTP_PROXY -e HTTPS_PROXY -e NO_PROXY --entrypoint=''"
        }
    }
    stages {
        stage("Tests & Coverage") {
            steps {
                script {
                    catchError(stageResult: 'FAILURE') {
                        sh """
                            tox_args="\$(git diff --name-only HEAD~10 | grep -Fxq -e requirements.txt -e requirements-dev.txt -e MANIFEST.in -e setup.py && echo '--recreate' || true)"
                            tox \$tox_args > results.txt 2>&1
                        """
                    }
                    results = readFile("results.txt").trim()
                    echo results
                    if (env.CHANGE_ID) {
                        commentOnPullRequest(msg: "### Build <span>#</span>${env.BUILD_NUMBER}\n```\n${results}\n```")
                    }
                }
            }
        }
        stage("Publish Coverage Report") {
            steps {
                catchError(buildResult: 'UNSTABLE', stageResult: 'FAILURE') {
                    withCredentials([string(credentialsId: "elliott-codecov-token", variable: "CODECOV_TOKEN")]) {
                        sh "codecov --token ${env.CODECOV_TOKEN}"
                    }
                }
            }
        }
        stage("Publish to PyPI") {
            when {
                buildingTag()
            }
            steps {
                sh "python3 setup.py bdist_wheel --universal"
                sh "python3 -m twine check dist/*"
                script { publishToPyPI() }
            }
        }
    }
}
